#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
WebRTC信令处理模块
负责处理WebRTC信令交换的WebSocket通信
"""

import json
import logging
import asyncio
import time
from aiohttp import web, WSMsgType
import uuid

logger = logging.getLogger(__name__)

class SignalingHandler:
    """WebRTC信令处理器，负责处理信令WebSocket连接和消息"""
    
    def __init__(self, connection_manager):
        """
        初始化信令处理器
        
        Args:
            connection_manager: WebRTC连接管理器实例
        """
        self.connection_manager = connection_manager
        self.websockets = {}  # client_id -> websocket
        self.sessions = {}    # session_id -> client_id
        logger.info("WebRTC信令处理器初始化完成")
    
    async def handle_websocket(self, request):
        """
        处理WebSocket连接请求
        
        Args:
            request: HTTP请求对象
            
        Returns:
            WebSocketResponse: WebSocket响应对象
        """
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        
        # 获取请求头和连接信息，用于调试
        headers = request.headers
        remote_ip = request.remote
        path = request.path
        host = request.host
        
        logger.info(f"WebRTC信令服务器收到新连接请求: 来源IP={remote_ip}, 路径={path}, 主机={host}")
        logger.info(f"WebRTC信令服务器收到请求头: {headers}")
        
        # 获取客户端ID (从查询参数或头部或生成新的)
        client_id = request.query.get('client_id') or headers.get('Client-ID') or headers.get('client-id')
        if not client_id:
            client_id = str(uuid.uuid4())
            logger.info(f"WebRTC信令服务器生成新客户端ID: {client_id}")
        else:
            logger.info(f"WebRTC信令服务器使用现有客户端ID: {client_id}")
            
        # 创建会话ID
        session_id = str(uuid.uuid4())
        self.websockets[client_id] = ws
        self.sessions[session_id] = client_id
        
        # 尝试关联WebSocket到WebRTCConnection
        # 这是关键改动 - 将信令WebSocket与WebRTC连接关联
        if hasattr(self.connection_manager, 'associate_websocket'):
            try:
                success = await self.connection_manager.associate_websocket(client_id, ws)
                if success:
                    logger.info(f"[SIGNALING] 成功将WebSocket关联到WebRTC连接 [ID: {client_id}]")
                else:
                    logger.warning(f"[SIGNALING] WebRTC连接对象尚不存在，将在需要时创建 [ID: {client_id}]")
            except Exception as e:
                logger.error(f"[SIGNALING] 关联WebSocket时出错: {e}")
                import traceback
                logger.error(f"[SIGNALING] 异常堆栈: {traceback.format_exc()}")
        else:
            logger.error(f"[SIGNALING] ConnectionManager缺少associate_websocket方法！")
        
        logger.info(f"WebRTC信令: 新的客户端连接已建立 [ID: {client_id}, 会话: {session_id}]")
        
        # 发送连接确认消息，包含服务器配置信息
        await ws.send_json({
            "type": "connected",
            "client_id": client_id,
            "session_id": session_id,
            "server_info": {
                "container_ip": request.host,  # 在Docker中这将是容器IP
                "timestamp": int(time.time())
            }
        })
        
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    await self.handle_text_message(client_id, ws, msg.data)
                elif msg.type == WSMsgType.BINARY:
                    await self.handle_binary_message(client_id, ws, msg.data)
                elif msg.type == WSMsgType.ERROR:
                    logger.error(f"WebSocket连接错误 [客户端: {client_id}]: {ws.exception()}")
                    break
        except Exception as e:
            logger.exception(f"处理WebSocket消息时出错 [客户端: {client_id}]: {e}")
        finally:
            # 清理连接
            await self.connection_manager.close_connection(client_id)
            self.websockets.pop(client_id, None)
            # 移除会话
            sessions_to_remove = [s_id for s_id, c_id in self.sessions.items() if c_id == client_id]
            for s_id in sessions_to_remove:
                self.sessions.pop(s_id, None)
                
            logger.info(f"WebRTC信令: 客户端断开连接 [ID: {client_id}]")
        
        return ws
    
    async def handle_text_message(self, client_id, ws, data):
        """
        处理文本消息
        
        Args:
            client_id: 客户端ID
            ws: WebSocket连接
            data: 消息数据
        """
        try:
            message = json.loads(data)
            msg_type = message.get('type')
            
            logger.debug(f"收到信令消息 [客户端: {client_id}, 类型: {msg_type}, 内容: {message}]")
            
            # 规范化消息类型（兼容不同的大小写和格式）
            normalized_type = str(msg_type).lower() if msg_type else ''
            
            # 提取payload，如果存在的话
            payload = message.get('payload', message)
            
            if normalized_type in ['offer', 'sdp_offer']:
                await self.connection_manager.handle_offer(client_id, payload, ws)
            elif normalized_type in ['answer', 'sdp_answer']:
                await self.connection_manager.handle_answer(client_id, payload)
            elif any(ice_type in normalized_type for ice_type in ['ice_candidate', 'ice-candidate', 'candidate']):
                await self.connection_manager.handle_ice_candidate(client_id, payload)
            elif normalized_type == 'close':
                await self.connection_manager.close_connection(client_id)
                await ws.send_json({"type": "closed"})
            elif normalized_type == 'ping':
                # 立即响应ping消息以保持心跳
                logger.debug(f"收到ping消息 [客户端: {client_id}], 立即响应pong")
                await ws.send_json({"type": "pong", "timestamp": message.get("timestamp", int(time.time()))})
            else:
                logger.warning(f"未知的信令消息类型 [客户端: {client_id}]: {normalized_type}")
                await ws.send_json({"type": "error", "message": f"未支持的消息类型: {normalized_type}"})
                
        except json.JSONDecodeError:
            logger.error(f"无效的JSON消息 [客户端: {client_id}]")
            await ws.send_json({"type": "error", "message": "无效的JSON格式"})
        except Exception as e:
            logger.exception(f"处理信令消息时出错 [客户端: {client_id}]: {e}")
            await ws.send_json({"type": "error", "message": str(e)})
    
    async def handle_binary_message(self, client_id, ws, data):
        """
        处理二进制消息
        
        Args:
            client_id: 客户端ID
            ws: WebSocket连接
            data: 二进制数据
        """
        logger.debug(f"收到二进制消息 [客户端: {client_id}, 大小: {len(data)} 字节]")
        
        # 如果需要处理二进制数据，可在此实现
        # 例如，可能是音频数据或其他二进制协议数据
        
    async def broadcast(self, message, exclude_client=None):
        """
        向所有连接的客户端广播消息
        
        Args:
            message: 要广播的消息
            exclude_client: 要排除的客户端ID (可选)
        """
        for client_id, ws in self.websockets.items():
            if exclude_client and client_id == exclude_client:
                continue
                
            if not ws.closed:
                if isinstance(message, dict):
                    await ws.send_json(message)
                elif isinstance(message, str):
                    await ws.send_str(message)
                else:
                    await ws.send_bytes(message)
    
    async def send_to_client(self, client_id, message):
        """
        发送消息给特定客户端
        
        Args:
            client_id: 目标客户端ID
            message: 要发送的消息
            
        Returns:
            bool: 是否发送成功
        """
        ws = self.websockets.get(client_id)
        if ws and not ws.closed:
            if isinstance(message, dict):
                await ws.send_json(message)
            elif isinstance(message, str):
                await ws.send_str(message)
            else:
                await ws.send_bytes(message)
            return True
        return False
