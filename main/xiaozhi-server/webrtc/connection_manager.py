#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
WebRTC连接管理器，负责处理和维护WebRTC连接
"""

import asyncio
import copy
import json
import logging
import time
import traceback
from concurrent.futures import ThreadPoolExecutor

import av
from aiortc import MediaStreamTrack, RTCIceServer, RTCPeerConnection, RTCSessionDescription, RTCConfiguration

from config.logger import setup_logging

# 导入拆分出的模块化类
from .modules.audio_track_processor import AudioTrackProcessor
from .modules.webrtc_connection import WebRTCConnection
from .modules.asr_helper import ASRHelper
from .modules.vad_helper import VADHelper
from .modules.audio_frame_handler import AudioFrameHandler

logger = setup_logging()


class ConnectionManager:
    """WebRTC连接管理器，负责处理和维护WebRTC连接"""
    
    def __init__(self, config):
        """
        初始化连接管理器
        
        Args:
            config: WebRTC配置对象
        """
        self.config = config
        self.peer_connections = {}  # client_id -> RTCPeerConnection
        self.data_channels = {}     # client_id -> RTCDataChannel  
        self.audio_processors = {}  # client_id -> AudioTrackProcessor
        self.pending_candidates = {}  # client_id -> [candidates]
        
        # 存储客户端的音频处理统计信息
        self.client_stats = {}  # client_id -> stats dict
        
        # 持久化的WebRTC连接对象
        self.webrtc_connections = {}  # client_id -> WebRTCConnection
        
        # 音频帧计数器
        self.audio_packet_counters = {}
        self.audio_bytes_counters = {}
        self.last_log_time = {}
        
        # 创建RTCConfiguration，包含ICE服务器
        ice_servers = [RTCIceServer(**server) for server in config.get_ice_servers()]
        self.rtc_configuration = RTCConfiguration(ice_servers)
        
        logger.info(f"WebRTC连接管理器初始化，ICE服务器数量: {len(ice_servers)}")
    
    async def create_peer_connection(self, client_id):
        """
        为客户端创建新的对等连接
        
        Args:
            client_id: 客户端ID
            
        Returns:
            RTCPeerConnection: 创建的对等连接
        """
        # 如果已存在，先关闭旧连接
        if client_id in self.peer_connections:
            await self.close_connection(client_id)
            
        # 创建新连接
        pc = RTCPeerConnection(configuration=self.rtc_configuration)
        self.peer_connections[client_id] = pc
        
        # 设置ICE连接状态变化回调
        @pc.on("iceconnectionstatechange")
        async def on_iceconnectionstatechange():
            logger.info(f"ICE连接状态变化 [客户端: {client_id}]: {pc.iceConnectionState}")
            if pc.iceConnectionState == "connected":
                logger.info(f"WebRTC: ICE连接已成功建立 [客户端: {client_id}]")
            elif pc.iceConnectionState == "completed":
                logger.info(f"WebRTC: ICE连接已完成并稳定 [客户端: {client_id}]")
            elif pc.iceConnectionState == "failed":
                logger.info(f"WebRTC: ICE连接失败 [客户端: {client_id}]")
                await self.handle_connection_failure(client_id)
        
        # 设置数据通道回调
        @pc.on("datachannel")
        def on_datachannel(channel):
            channel_id = channel.label
            logger.info(f"数据通道已创建 [客户端: {client_id}, 通道: {channel_id}]")
            self.data_channels[f"{client_id}_{channel_id}"] = channel
            
            @channel.on("message")
            def on_message(message):
                if isinstance(message, str):
                    try:
                        data = json.loads(message)
                        logger.info(f"收到数据通道消息 [客户端: {client_id}, 通道: {channel_id}]: {data}")
                    except json.JSONDecodeError:
                        logger.info(f"收到数据通道消息 [客户端: {client_id}, 通道: {channel_id}]: {message}")
                else:
                    logger.info(f"收到数据通道二进制消息 [客户端: {client_id}, 通道: {channel_id}]: {len(message)} 字节")
        
        # 设置音频/视频轨道回调
        @pc.on("track")
        def on_track(track):
            if track.kind == "audio":
                logger.info(f"收到音频轨道 [客户端: {client_id}]")
                
                # 创建处理音频帧的回调函数
                async def frame_callback(frame):
                    try:
                        # 处理音频帧
                        await self.process_audio_frame(frame, client_id)
                    except Exception as e:
                        logger.error(f"处理音频帧时出错: {e}")
                        import traceback
                        logger.error(f"堆栈跟踪: {traceback.format_exc()}")
                
                # 创建音频处理器
                processor = AudioTrackProcessor(track, on_frame=frame_callback)
                self.audio_processors[client_id] = processor
                
                # 返回处理后的轨道
                return processor
            elif track.kind == "video":
                logger.info(f"收到视频轨道 [客户端: {client_id}]")
                # 不处理视频轨道，直接返回
                return track
        
        return pc
    
    async def send_websocket_message(self, websocket, message):
        """
        尝试使用各种方法发送WebSocket消息
        
        Args:
            websocket: WebSocket对象
            message: 要发送的消息对象
            
        Returns:
            bool: 是否成功发送
        """
        if not self.is_websocket_open(websocket):
            logger.error(f"WebSocket不可用，无法发送消息")
            return False
        
        # 输出详细的WebSocket类型信息以便调试
        logger.info(f"WebSocket类型: {type(websocket)}")
            
        # 首先检查是否有send_json方法 (对aiohttp.WebSocketResponse)
        if hasattr(websocket, 'send_json'):
            try:
                await websocket.send_json(message)
                logger.info(f"WebSocket.send_json方法成功")
                return True
            except Exception as e:
                logger.warning(f"WebSocket.send_json方法失败: {e}")
        
        # 尝试使用send方法 (对标准WebSocket)
        if hasattr(websocket, 'send'):
            try:
                await websocket.send(json.dumps(message))
                logger.info(f"WebSocket.send方法成功")
                return True
            except Exception as e:
                logger.warning(f"WebSocket.send方法失败: {e}")
            
        # 尝试使用send_str方法 (对aiohttp.WebSocketResponse的另一种方式)
        if hasattr(websocket, 'send_str'):
            try:
                await websocket.send_str(json.dumps(message))
                logger.info(f"WebSocket.send_str方法成功")
                return True
            except Exception as e:
                logger.warning(f"WebSocket.send_str方法失败: {e}")
            
        logger.error(f"所有WebSocket发送方法均失败")
        return False
    
    def is_websocket_open(self, ws):
        """
        检查WebSocket是否打开并可用
        
        Args:
            ws: WebSocket连接对象
            
        Returns:
            bool: WebSocket是否可用
        """
        if ws is None:
            return False
            
        # 检查常见的WebSocket属性
        if hasattr(ws, 'open'):
            return ws.open
        if hasattr(ws, 'closed'):
            return not ws.closed
        if hasattr(ws, 'readyState'):
            # 浏览器WebSocket的readyState: 0=CONNECTING, 1=OPEN, 2=CLOSING, 3=CLOSED
            return ws.readyState == 1
            
        # 如果没有标准属性，尝试检查其他可能的状态指示器
        for attr in ['connected', 'is_connected', 'active', 'is_active']:
            if hasattr(ws, attr) and callable(getattr(ws, attr)):
                try:
                    return getattr(ws, attr)()
                except:
                    pass
            elif hasattr(ws, attr):
                return bool(getattr(ws, attr))
                
        # 默认假设它是打开的，除非有明确证据表明它是关闭的
        logger.warning(f"无法确定WebSocket状态，假设它是打开的")
        return True
    
    async def associate_websocket(self, client_id, websocket):
        """
        关联WebSocket到WebRTC连接
        
        Args:
            client_id: 客户端ID
            websocket: WebSocket连接对象
        """
        if client_id not in self.webrtc_connections:
            self.webrtc_connections[client_id] = WebRTCConnection(client_id=client_id)
            logger.info(f"创建了新的WebRTCConnection [客户端: {client_id}]")
        
        self.webrtc_connections[client_id].websocket = websocket
        logger.info(f"成功关联WebSocket到WebRTCConnection [客户端: {client_id}]")
    
    async def handle_offer(self, client_id, offer_data, websocket=None):
        """
        处理来自客户端的Offer
        
        参数:
        client_id: 客户端ID
        offer_data: Offer数据
        websocket: WebSocket连接对象（可选）
        """
        try:
            logger.info(f"处理Offer [客户端: {client_id}]")
            
            # 首先尝试关联WebSocket，确保后续操作可以使用它
            if websocket:
                # 检查WebSocket是否可用
                if self.is_websocket_open(websocket):
                    # 立即关联WebSocket到连接
                    await self.associate_websocket(client_id, websocket)
                    logger.info(f"在处理Offer前已关联WebSocket [客户端: {client_id}]")
                else:
                    logger.warning(f"传入的WebSocket不可用，无法关联 [客户端: {client_id}]")
            else:
                logger.warning(f"无可用的WebSocket连接传入handle_offer [客户端: {client_id}]")
            
            # 1. 解析offer_data
            type_ = None
            sdp = None
            
            if isinstance(offer_data, dict):
                # 如果offer_data是字典，尝试获取type和sdp字段
                if 'type' in offer_data and 'sdp' in offer_data:
                    type_ = offer_data['type']
                    sdp = offer_data['sdp']
                elif 'sdp' in offer_data and isinstance(offer_data['sdp'], dict):
                    # 处理嵌套的sdp对象
                    sdp_obj = offer_data['sdp']
                    if 'type' in sdp_obj and 'sdp' in sdp_obj:
                        type_ = sdp_obj['type']
                        sdp = sdp_obj['sdp']
            elif isinstance(offer_data, str):
                # 如果offer_data是字符串，直接将其作为sdp值，type设为"offer"
                type_ = "offer"
                sdp = offer_data
            else:
                logger.error(f"无法解析的offer_data格式: {type(offer_data)} [客户端: {client_id}]")
                return
                
            if not type_ or not sdp:
                logger.error(f"无效的Offer格式 [客户端: {client_id}]")
                return
            
            # 2. 创建RTCSessionDescription
            offer = RTCSessionDescription(sdp=sdp, type=type_)
            
            # 3. 创建PeerConnection
            pc = await self.create_peer_connection(client_id)
            
            # 4. 设置远程描述（Offer）
            await pc.setRemoteDescription(offer)
            
            # 5. 创建Answer
            answer = await pc.createAnswer()
            
            # 6. 设置本地描述（Answer）
            await pc.setLocalDescription(answer)
            
            # 7. 发送Answer给客户端
            answer_data = {
                "type": "answer",
                "sdp": {
                    "type": pc.localDescription.type,
                    "sdp": pc.localDescription.sdp
                },
                "client_id": client_id
            }
            
            logger.info(f"准备发送Answer [客户端: {client_id}]")
            
            # 发送CONNECTED消息，告知客户端服务器已准备好
            connected_message = {
                "type": "connected",
                "payload": {
                    "client_id": client_id,
                    "timestamp": int(time.time())
                }
            }
            
            sent_answer = False
            
            # 尝试方法1: 使用提供的websocket
            if websocket:
                logger.info(f"WebSocket检查 [客户端: {client_id}]: 类型={type(websocket)}, 属性={dir(websocket)[:5]}...")
                
                # 输出更多详细的WebSocket状态信息
                ws_status = "unknown"
                if hasattr(websocket, 'open'):
                    ws_status = f"open={websocket.open}"
                elif hasattr(websocket, 'closed'):
                    ws_status = f"closed={websocket.closed}"
                elif hasattr(websocket, 'readyState'):
                    ws_status = f"readyState={websocket.readyState}"
                logger.info(f"WebSocket状态详情 [客户端: {client_id}]: {ws_status}")
                
                if self.is_websocket_open(websocket):
                    try:
                        # 先发送CONNECTED消息
                        logger.info(f"发送CONNECTED消息 [客户端: {client_id}]")
                        if await self.send_websocket_message(websocket, connected_message):
                            logger.info(f"CONNECTED消息发送成功 [客户端: {client_id}]")
                        else:
                            logger.error(f"CONNECTED消息发送失败 [客户端: {client_id}]")
                            raise Exception("CONNECTED消息发送失败")
                        
                        # 然后发送Answer
                        logger.info(f"准备通过传入的WebSocket发送Answer [客户端: {client_id}]")
                        if await self.send_websocket_message(websocket, answer_data):
                            logger.info(f"使用传入的WebSocket发送Answer成功 [客户端: {client_id}]")
                            sent_answer = True
                        else:
                            logger.error(f"Answer消息发送失败 [客户端: {client_id}]")
                            raise Exception("Answer消息发送失败")
                    except Exception as e:
                        logger.error(f"使用传入的WebSocket发送Answer失败: {e} [客户端: {client_id}]")
                        import traceback
                        logger.error(f"发送Answer异常堆栈: {traceback.format_exc()}")
                else:
                    logger.error(f"传入的WebSocket不可用 [客户端: {client_id}], 属性open: {hasattr(websocket, 'open')}, 状态: {getattr(websocket, 'open', None)}")
            
            # 尝试方法2: 使用已关联的WebRTCConnection中的websocket
            if not sent_answer and client_id in self.webrtc_connections:
                conn = self.webrtc_connections.get(client_id)
                if conn:
                    logger.info(f"检查WebRTCConnection对象 [客户端: {client_id}]: websocket存在={conn.websocket is not None}")
                    
                    if self.is_websocket_open(conn.websocket):
                        try:
                            # 先发送CONNECTED消息
                            logger.info(f"发送CONNECTED消息 [客户端: {client_id}]")
                            if await self.send_websocket_message(conn.websocket, connected_message):
                                logger.info(f"CONNECTED消息发送成功 [客户端: {client_id}]")
                            else:
                                logger.error(f"CONNECTED消息发送失败 [客户端: {client_id}]")
                                raise Exception("CONNECTED消息发送失败")
                            
                            # 然后发送Answer
                            logger.info(f"准备通过已关联的WebSocket发送Answer [客户端: {client_id}]")
                            if await self.send_websocket_message(conn.websocket, answer_data):
                                logger.info(f"使用关联的WebSocket发送Answer成功 [客户端: {client_id}]")
                                sent_answer = True
                            else:
                                logger.error(f"Answer消息发送失败 [客户端: {client_id}]")
                                raise Exception("Answer消息发送失败")
                        except Exception as e:
                            logger.error(f"使用关联的WebSocket发送Answer失败: {e} [客户端: {client_id}]")
                            import traceback
                            logger.error(f"发送Answer异常堆栈: {traceback.format_exc()}")
                    else:
                        logger.error(f"关联的WebSocket不可用 [客户端: {client_id}], 属性open: {hasattr(conn.websocket, 'open') if conn.websocket else False}, 状态: {getattr(conn.websocket, 'open', None) if conn.websocket else None}")
            
            # 尝试方法3: 创建WebRTCConnection并存储Answer到待发送队列
            if not sent_answer:
                # 创建或获取WebRTCConnection对象
                if client_id not in self.webrtc_connections:
                    self.webrtc_connections[client_id] = WebRTCConnection(client_id=client_id)
                    logger.info(f"创建了新的WebRTCConnection [客户端: {client_id}]")
                
                # 获取WebRTCConnection对象
                conn = self.webrtc_connections[client_id]
                
                # 关键修复: 只在当前没有有效WebSocket时才设置新的WebSocket
                if websocket and (not conn.websocket or not self.is_websocket_open(conn.websocket)):
                    # 保存旧的WebSocket用于日志
                    old_ws = conn.websocket
                    conn.websocket = websocket
                    logger.info(f"成功关联新的WebSocket到WebRTCConnection [客户端: {client_id}], 替换旧WebSocket: {old_ws is not None}")
                    
                # 只有在WebSocket有效时才尝试发送
                if self.is_websocket_open(conn.websocket):
                    # 尝试立即发送answer
                    try:
                        logger.info(f"直接发送Answer尝试 [客户端: {client_id}], WebSocket类型: {type(conn.websocket)}")
                        # 检查WebSocket对象类型和方法
                        if hasattr(conn.websocket, 'send_json'):
                            logger.info(f"使用send_json方法发送Answer [客户端: {client_id}]")
                            await conn.websocket.send_json(answer_data)
                        else:
                            logger.info(f"使用send方法发送Answer [客户端: {client_id}]")
                            await conn.websocket.send(json.dumps(answer_data))
                        logger.info(f"使用关联的WebSocket直接发送Answer成功 [客户端: {client_id}]")
                        sent_answer = True
                    except Exception as e:
                        logger.error(f"使用关联的WebSocket发送Answer失败: {str(e)} [客户端: {client_id}]")
                        import traceback
                        logger.error(f"直接发送Answer异常堆栈: {traceback.format_exc()}")
                else:
                    logger.warning(f"无可用的WebSocket连接传入handle_offer [客户端: {client_id}]")
                
                # 将Answer存储到连接对象中
                conn.pending_answer = answer_data
                logger.info(f"将CONNECTED消息和Answer存储到连接对象 [客户端: {client_id}]")
                logger.info(f"Answer待发送数据: {answer_data['type']}, SDP类型: {answer_data['sdp']['type']}")
                    
                # 检查是否有可用的WebSocket连接用于重试
                if self.is_websocket_open(conn.websocket):
                    logger.info(f"WebSocket连接可用，启动重试任务 [客户端: {client_id}]")
                    asyncio.create_task(self._retry_send_answer(client_id))
                else:
                    logger.warning(f"没有可用的WebSocket连接用于重试 [客户端: {client_id}]，将等待WebSocket重连")
            
            # 8. 如果有待处理的ICE候选者，添加它们
            if client_id in self.pending_candidates:
                for candidate_data in self.pending_candidates[client_id]:
                    await self.handle_ice_candidate(client_id, candidate_data)
        
                # 清空待处理的候选者
                self.pending_candidates.pop(client_id, None)
                
        except Exception as e:
            logger.error(f"处理Offer时出错 [客户端: {client_id}]: {e}")
            import traceback
            logger.error(f"堆栈跟踪: {traceback.format_exc()}")
    
    async def handle_answer(self, client_id, answer_data):
        """
        处理客户端发送的Answer
        
        Args:
            client_id: 客户端ID
            answer_data: Answer数据
        """
        logger.info(f"收到Answer [客户端: {client_id}]")
        
        pc = self.peer_connections.get(client_id)
        if not pc:
            logger.warning(f"未找到对应的PeerConnection [客户端: {client_id}]")
            return
            
        # 1. 提取SDP信息
        try:
            answer_sdp = answer_data.get("sdp", {})
            type_ = answer_sdp.get("type")
            sdp = answer_sdp.get("sdp")
            
            if not type_ or not sdp:
                logger.error(f"无效的Answer格式 [客户端: {client_id}]")
                return
                
            # 2. 创建RTCSessionDescription
            answer = RTCSessionDescription(sdp=sdp, type=type_)
            
            # 3. 设置远程描述（Answer）
            await pc.setRemoteDescription(answer)
            logger.info(f"设置远程描述成功 [客户端: {client_id}]")
            
        except Exception as e:
            logger.error(f"处理Answer时出错 [客户端: {client_id}]: {e}")
            import traceback
            logger.error(f"堆栈跟踪: {traceback.format_exc()}")
    
    async def handle_ice_candidate(self, client_id: str, candidate_data):
        """
        处理ICE候选者
        
        Args:
            client_id: 客户端ID
            candidate_data: ICE候选者数据，可以是字典或字符串
        """
        # 获取对应的PeerConnection
        pc = self.peer_connections.get(client_id)
        
        # 如果没有找到对应的PeerConnection，则缓存候选者
        if not pc:
            if client_id not in self.pending_candidates:
                self.pending_candidates[client_id] = []
            self.pending_candidates[client_id].append(candidate_data)
            logger.info(f"缓存ICE候选者 [客户端: {client_id}]")
            return
            
        # 从候选者数据中提取信息
        try:
            # 处理不同格式的候选者数据
            candidate = ""
            sdpMid = ""
            sdpMLineIndex = 0
            
            # 如果是字符串格式（客户端直接发送candidate字符串）
            if isinstance(candidate_data, str):
                logger.info(f"收到字符串格式的ICE候选者 [客户端: {client_id}]")
                try:
                    # 尝试解析JSON字符串
                    json_data = json.loads(candidate_data)
                    if isinstance(json_data, dict):
                        if "candidate" in json_data:
                            ice_candidate = json_data
                            candidate = ice_candidate.get("candidate", "")
                            sdpMid = ice_candidate.get("sdpMid", "")
                            sdpMLineIndex = ice_candidate.get("sdpMLineIndex", 0)
                        else:
                            candidate = json_data.get("candidate", "")
                            sdpMid = json_data.get("sdpMid", "")
                            sdpMLineIndex = json_data.get("sdpMLineIndex", 0)
                    elif isinstance(json_data, str):
                        # 如果解析出的还是字符串，则认为直接是candidate值
                        candidate = json_data
                except json.JSONDecodeError:
                    # 不是JSON格式，直接使用字符串作为candidate值
                    candidate = candidate_data
            # 如果是字典格式（标准格式）
            elif isinstance(candidate_data, dict):
                if "candidate" in candidate_data:
                    if isinstance(candidate_data["candidate"], dict):
                        ice_candidate = candidate_data.get("candidate", {})
                        candidate = ice_candidate.get("candidate", "")
                        sdpMid = ice_candidate.get("sdpMid", "")
                        sdpMLineIndex = ice_candidate.get("sdpMLineIndex", 0)
                    else:  # candidate字段直接是字符串
                        candidate = candidate_data.get("candidate", "")
                        sdpMid = candidate_data.get("sdpMid", "")
                        sdpMLineIndex = candidate_data.get("sdpMLineIndex", 0)
                else:  # candidate_data本身就包含了所需字段
                    candidate = candidate_data.get("candidate", "")
                    sdpMid = candidate_data.get("sdpMid", "")
                    sdpMLineIndex = candidate_data.get("sdpMLineIndex", 0)
            
            if candidate:
                # 创建RTCIceCandidate并添加到PeerConnection
                from aiortc import RTCIceCandidate
                
                try:
                    # 直接使用成功的对象方式处理
                    # 先统一格式，确保开头有candidate:
                    if not candidate.startswith('candidate:'):
                        candidate = 'candidate:' + candidate
                        
                    # 解析候选者字符串中的必要参数
                    parts = candidate.split(' ')
                    if len(parts) >= 10 and parts[0].startswith('candidate:'):
                        # 格式为: candidate:foundation component protocol priority ip port type ... 
                        foundation = parts[0].replace('candidate:', '')
                        component = int(parts[1])
                        protocol = parts[2]
                        priority = int(parts[3])
                        ip = parts[4]
                        port = int(parts[5])
                        type = parts[7]
                        
                        # 创建RTCIceCandidate对象
                        ice = RTCIceCandidate(
                            foundation=foundation,
                            component=component,
                            protocol=protocol,
                            priority=priority,
                            ip=ip,
                            port=port,
                            type=type,
                            sdpMid=sdpMid,
                            sdpMLineIndex=sdpMLineIndex
                        )
                        
                        # 添加到对等连接
                        await pc.addIceCandidate(ice)
                        logger.info(f"添加ICE候选者成功 [客户端: {client_id}]")
                    else:
                        logger.error(f"无法解析候选者字符串: {candidate}")
                        # 尝试使用内部方法
                        pc._addRemoteIceCandidate(
                            sdpMid=sdpMid,
                            sdpMLineIndex=sdpMLineIndex,
                            candidate=candidate
                        )
                        logger.info(f"使用备用方法添加ICE候选者成功 [客户端: {client_id}]")
                except Exception as e:
                    logger.error(f"处理ICE候选者时出错: {e}")
                    logger.error(f"原始候选者数据: {candidate_data}")
                    # 尝试最后的方法 - 重新触发ICE收集
                    try:
                        await pc.setLocalDescription(await pc.createAnswer())
                        logger.info(f"重新触发了本地ICE收集过程 [客户端: {client_id}]")
                    except Exception as answer_err:
                        logger.error(f"重新触发ICE收集失败: {answer_err}")
           
            else:
                logger.warning(f"空的ICE候选者 [客户端: {client_id}]: {candidate_data}")
                
        except Exception as e:
            logger.error(f"处理ICE候选者时出错 [客户端: {client_id}]: {e}")
            import traceback
            logger.error(f"堆栈跟踪: {traceback.format_exc()}")
            logger.error(f"原始候选者数据: {candidate_data}")
    
    async def process_audio(self, client_id, audio_data):
        """
        处理客户端发送的音频数据
        
        Args:
            client_id: 客户端ID
            audio_data: 音频数据
        """
        logger.debug(f"处理音频数据 [客户端: {client_id}], 大小: {len(audio_data)} 字节")
        
        # TODO: 实现音频处理逻辑
        
    async def _convert_audio_to_pcm(self, frame):
        """将音频帧转换为PCM格式"""
        # 使用PyAV将音频帧转换为NumPy数组，再转为bytes
        ndarray = frame.to_ndarray()
        return ndarray.tobytes()
    
    async def associate_websocket(self, client_id, websocket):
        """
        关联WebRTC连接和WebSocket连接
        
        参数:
        client_id: 客户端 ID
        websocket: 客户端的WebSocket连接
        
        返回:
        bool: 关联是否成功
        """
        logger.info(f"尝试关联WebSocket [客户端: {client_id}]")
        
        # 检查WebSocket是否可用 - 使用统一的检查方法
        if not self.is_websocket_open(websocket):
            logger.error(f"无法关联无效的WebSocket [客户端: {client_id}]")
            return False
            
        try:
            # 创建或获取WebRTCConnection对象
            if client_id not in self.webrtc_connections:
                self.webrtc_connections[client_id] = WebRTCConnection(client_id=client_id)
                logger.info(f"为WebSocket关联创建了新的WebRTCConnection [客户端: {client_id}]")
            
            conn = self.webrtc_connections[client_id]
            
            # 关键修复: 只在当前没有有效WebSocket时才设置新的WebSocket
            if not conn.websocket or not self.is_websocket_open(conn.websocket):
                # 保存旧的WebSocket用于日志
                old_ws = conn.websocket
                conn.websocket = websocket
                logger.info(f"成功关联WebSocket [客户端: {client_id}], 替换旧WebSocket: {old_ws is not None}")
            else:
                logger.info(f"保留现有有效WebSocket [客户端: {client_id}]")
            
            # 如果有待发送的Answer，尝试立即发送
            if hasattr(conn, 'pending_answer') and conn.pending_answer:
                try:
                    logger.info(f"尝试发送待处理的Answer [客户端: {client_id}]")
                    answer_json = json.dumps(conn.pending_answer)
                    
                    # 根据WebSocket对象类型选择发送方法
                    if hasattr(conn.websocket, 'send_json'):
                        await conn.websocket.send_json(conn.pending_answer)
                    else:
                        await conn.websocket.send(answer_json)
                        
                    logger.info(f"成功发送待处理的Answer [客户端: {client_id}]")
                    conn.pending_answer = None  # 清除待处理的Answer
                except Exception as e:
                    logger.error(f"发送待处理Answer失败 [客户端: {client_id}]: {e}")
                    return False
            
            return True
        except Exception as e:
            logger.error(f"[SERVER-CONNECTION] 关联WebSocket失败: {e}")
            return False
        
    async def process_audio_frame(self, frame, client_id):
        """
        处理WebRTC音频帧
        
        参数:
        frame: 音频帧
        client_id: 客户端 ID
        """
        # 如果未初始化AudioFrameHandler，则创建一个实例
        if not hasattr(self, 'audio_frame_handler'):
            self.audio_frame_handler = AudioFrameHandler()
            
        # 调用AudioFrameHandler处理音频帧
        return await self.audio_frame_handler.process_audio_frame(frame, client_id, self.webrtc_connections)

    async def handle_connection_failure(self, client_id):
        """
        处理连接失败
        
        Args:
            client_id: 客户端ID
        """
        logger.warning(f"WebRTC连接失败 [客户端: {client_id}]")
        # 这里可以实现重连逻辑，或者通知客户端切换到备用通信方式
    
    # 简化设计，移除了注册连接的方法
        
    async def close_connection(self, client_id):
        """
        关闭并清理WebRTC连接
        
        Args:
            client_id: 客户端 ID
        """
        # 关闭PeerConnection
        pc = self.peer_connections.get(client_id)
        if pc:
            await pc.close()
            self.peer_connections.pop(client_id, None)
            
        # 清理关联的资源
        self.audio_processors.pop(client_id, None)
        
        # 清理持久化的WebRTC连接对象
        self.webrtc_connections.pop(client_id, None)
        
        # 清理数据通道
        channels_to_remove = [k for k in self.data_channels if k.startswith(f"{client_id}_")]
        for channel_key in channels_to_remove:
            self.data_channels.pop(channel_key, None)
            
        logger.info(f"已关闭客户端 {client_id} 的连接")
    
    async def _retry_send_answer(self, client_id, max_retries=10, retry_interval=1.0):
        """
        尝试多次发送Answer直到成功
        
        Args:
            client_id: 客户端ID
            max_retries: 最大重试次数
            retry_interval: 重试间隔(秒)
        """
        logger.info(f"[重试机制] 启动Answer重试发送进程 [客户端: {client_id}, 最大重试: {max_retries}, 间隔: {retry_interval}s]")
        
        if client_id not in self.webrtc_connections:
            logger.error(f"[重试机制] WebRTCConnection对象不存在 [客户端: {client_id}]")
            return
            
        conn = self.webrtc_connections[client_id]
        logger.info(f"[重试机制] 获取到WebRTCConnection对象 [客户端: {client_id}, websocket存在: {conn.websocket is not None}]")
        
        # 检查是否有待发送的Answer
        if not hasattr(conn, 'pending_answer') or conn.pending_answer is None:
            logger.error(f"[重试机制] 没有待发送的Answer [客户端: {client_id}]")
            return
        else:
            answer_type = conn.pending_answer.get('type', 'unknown')
            sdp_info = conn.pending_answer.get('sdp', {})
            sdp_type = sdp_info.get('type', 'unknown') if isinstance(sdp_info, dict) else 'unknown'
            logger.info(f"[重试机制] 待发送Answer信息 [客户端: {client_id}, 类型: {answer_type}, SDP类型: {sdp_type}]")
        
        # 创建CONNECTED消息，如果不存在
        if not hasattr(conn, 'pending_connected_message') or conn.pending_connected_message is None:
            conn.pending_connected_message = {
                "type": "connected",
                "payload": {
                    "client_id": client_id,
                    "timestamp": int(time.time())
                }
            }
            logger.info(f"[重试机制] 创建CONNECTED消息 [客户端: {client_id}]")
            
        retries = 0
        while retries < max_retries:
            logger.info(f"[重试机制] 开始第{retries+1}次尝试 [客户端: {client_id}]")
            
            # 检查WebSocket连接 - 使用统一的检查方法
            if conn.websocket:
                ws_status = "open" if self.is_websocket_open(conn.websocket) else "closed"
                logger.info(f"[重试机制] WebSocket状态 [客户端: {client_id}, 状态: {ws_status}, 类型: {type(conn.websocket)}]")
                
                if self.is_websocket_open(conn.websocket):
                    try:
                        # 先发送CONNECTED消息
                        if hasattr(conn, 'pending_connected_message') and conn.pending_connected_message:
                            logger.info(f"[重试机制] 准备发送CONNECTED消息 [客户端: {client_id}]")
                            
                            # 使用统一的发送方法
                            if await self.send_websocket_message(conn.websocket, conn.pending_connected_message):
                                logger.info(f"[重试机制] 发送CONNECTED消息成功 [客户端: {client_id}]")
                                # 等待一小段时间，确保客户端收到CONNECTED消息
                                await asyncio.sleep(0.2)
                            else:
                                logger.error(f"[重试机制] 发送CONNECTED消息失败 [客户端: {client_id}]")
                                raise Exception("CONNECTED消息发送失败")
                        
                        # 然后发送Answer
                        logger.info(f"[重试机制] 准备发送Answer [客户端: {client_id}]")
                        
                        # 使用统一的发送方法
                        if await self.send_websocket_message(conn.websocket, conn.pending_answer):
                            logger.info(f"[重试机制] 重试发送Answer成功 [客户端: {client_id}, 尝试次数: {retries+1}]")
                        else:
                            logger.error(f"[重试机制] 发送Answer失败 [客户端: {client_id}]")
                            raise Exception("Answer消息发送失败")
                        
                        # 清除待发送的消息
                        conn.pending_connected_message = None
                        conn.pending_answer = None
                        return True
                    except Exception as e:
                        logger.error(f"[重试机制] 重试发送Answer失败 [客户端: {client_id}, 尝试次数: {retries+1}]: {e}")
                        import traceback
                        logger.error(f"[重试机制] 异常堆栈: {traceback.format_exc()}")
                        
                        # 检查异常是否表明WebSocket已关闭
                        if "closed" in str(e).lower() or "not open" in str(e).lower():
                            logger.warning(f"[重试机制] WebSocket已关闭，标记为无效 [客户端: {client_id}]")
                            # 将WebSocket标记为无效，以便下次不再尝试使用
                            conn.websocket = None
            else:
                logger.error(f"[重试机制] WebSocket对象不存在 [客户端: {client_id}, 尝试次数: {retries+1}]")
            
            # 如果发送失败，等待后重试
            logger.info(f"[重试机制] 等待{retry_interval}秒后重试 [客户端: {client_id}, 当前重试次数: {retries+1}]")
            await asyncio.sleep(retry_interval)
            retries += 1
            
        logger.error(f"[重试机制] 多次尝试发送Answer均失败 [客户端: {client_id}, 最大尝试次数: {max_retries}]")
        return False
        
    async def close_all_connections(self):
        """关闭所有连接"""
        logger.info("关闭所有WebRTC连接...")
        
        for client_id in list(self.peer_connections.keys()):
            await self.close_connection(client_id)
