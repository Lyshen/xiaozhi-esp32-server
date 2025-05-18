#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
WebRTC连接管理器
负责创建、管理和维护WebRTC连接
"""

import asyncio
import json
import logging
import weakref
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer
from aiortc.contrib.media import MediaStreamTrack
import av

logger = logging.getLogger(__name__)

class AudioTrackProcessor(MediaStreamTrack):
    """处理音频轨道的MediaStreamTrack子类"""
    
    kind = "audio"  # MediaStreamTrack类型
    
    def __init__(self, track, on_frame=None):
        """
        初始化音频处理器
        
        Args:
            track: 源音频轨道
            on_frame: 处理音频帧的回调函数
        """
        super().__init__()
        self.track = track
        self.on_frame = on_frame
        self._queue = asyncio.Queue()
        self._start = None
        
    async def recv(self):
        """
        接收音频帧
        
        Returns:
            av.AudioFrame: 处理后的音频帧
        """
        frame = await self.track.recv()
        
        # 如果有回调函数，处理音频帧
        if self.on_frame:
            await self.on_frame(frame)
            
        # 返回处理后的帧
        return frame


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
            if pc.iceConnectionState == "failed":
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
                    logger.debug(f"数据通道收到文本消息 [客户端: {client_id}, 通道: {channel_id}]: {message[:100]}...")
                else:
                    logger.debug(f"数据通道收到二进制消息 [客户端: {client_id}, 通道: {channel_id}]: {len(message)} 字节")
        
        # 设置轨道回调
        @pc.on("track")
        def on_track(track):
            logger.info(f"收到媒体轨道 [客户端: {client_id}, 类型: {track.kind}]")
            if track.kind == "audio":
                # 创建并存储音频处理器
                audio_processor = AudioTrackProcessor(track, self.process_audio_frame)
                self.audio_processors[client_id] = audio_processor
                
                # 将音频处理器添加到连接中
                pc.addTrack(audio_processor)
                
        # 将任何待处理的ICE候选者应用到连接
        if client_id in self.pending_candidates:
            for candidate in self.pending_candidates[client_id]:
                await pc.addIceCandidate(candidate)
            del self.pending_candidates[client_id]
                
        logger.info(f"已为客户端 {client_id} 创建新的对等连接")
        return pc
    
    async def handle_offer(self, client_id, offer_data, websocket=None):
        """
        处理客户端发送的Offer
        
        Args:
            client_id: 客户端ID
            offer_data: Offer数据
            websocket: WebSocket连接
        """
        logger.info(f"收到Offer [客户端: {client_id}]: {offer_data}")
        
        if websocket is None:
            logger.error(f"缺少websocket连接，无法发送应答 [客户端: {client_id}]")
            return
        
        pc = None
        try:
            # 创建对等连接
            pc = await self.create_peer_connection(client_id)
            
            # 检查offer数据格式
            # 兼容不同的offer格式（客户端可能发送sdp或description字段）
            sdp = None
            offer_type = "offer"
            
            # 检查是否包含payload字段（cosplay-client的格式）
            if isinstance(offer_data, dict) and "payload" in offer_data and isinstance(offer_data["payload"], dict):
                # 从 payload 中提取数据
                logger.info(f"分析payload格式: {offer_data['payload']}")
                
                if "sdp" in offer_data["payload"]:
                    sdp = offer_data["payload"]["sdp"]
                    if "type" in offer_data["payload"]:
                        offer_type = offer_data["payload"]["type"]
                offer_data = offer_data["payload"]  # 更新offer_data以便后续处理
            
            # 处理直接包含sdp的格式
            if sdp is None and isinstance(offer_data, dict):
                # 尝试各种可能的字段名
                if "sdp" in offer_data:
                    sdp = offer_data["sdp"]
                elif "description" in offer_data:
                    if isinstance(offer_data["description"], dict) and "sdp" in offer_data["description"]:
                        sdp = offer_data["description"]["sdp"]
                    else:
                        sdp = offer_data["description"]
                
                # 获取类型
                if "type" in offer_data:
                    offer_type = offer_data["type"]
                elif "description" in offer_data and isinstance(offer_data["description"], dict) and "type" in offer_data["description"]:
                    offer_type = offer_data["description"]["type"]
            elif sdp is None:
                # 如果不是字典，尝试直接使用
                sdp = offer_data
                
            # 验证SDP是否有效
            if not sdp:
                logger.error(f"无效的Offer数据 [客户端: {client_id}]: {offer_data}")
                await websocket.send_json({"type": "error", "message": "Invalid offer: missing SDP"})
                return
                
            logger.info(f"最终解析的SDP类型: {offer_type}")
            logger.info(f"最终解析的SDP内容前100字符: {sdp[:100] if isinstance(sdp, str) else sdp}...")
            
            # 设置远程描述
            offer = RTCSessionDescription(sdp=sdp, type=offer_type)
            await pc.setRemoteDescription(offer)
            
            # 创建应答
            answer = await pc.createAnswer()
            await pc.setLocalDescription(answer)
            
            # 确保Answer格式正确，包含type和sdp字段
            response = {
                "type": "answer",
                "payload": {
                    "type": "answer",
                    "sdp": pc.localDescription.sdp
                }
            }
            
            logger.info(f"创建Answer完成 [客户端: {client_id}]，响应格式：{response}")
            
            # 处理之前存储的待处理ICE候选者
            if client_id in self.pending_candidates and pc.remoteDescription:
                logger.info(f"处理待处理的ICE候选者 [客户端: {client_id}]: {len(self.pending_candidates[client_id])}个")
                for candidate in self.pending_candidates[client_id]:
                    try:
                        await pc.addIceCandidate(candidate)
                    except Exception as ice_error:
                        logger.warning(f"添加待处理ICE候选者失败 [客户端: {client_id}]: {ice_error}")
                self.pending_candidates.pop(client_id, None)
            
            # 发送应答给客户端
            await websocket.send_json(response)
            logger.info(f"已发送Answer [客户端: {client_id}]")
            
        except Exception as e:
            logger.exception(f"处理Offer时出错 [客户端: {client_id}]: {e}")
            error_response = {"type": "error", "message": f"Error processing offer: {str(e)}"}
            try:
                await websocket.send_json(error_response)
            except Exception as ws_error:
                logger.error(f"发送错误响应失败 [客户端: {client_id}]: {ws_error}")
            
            # 发生错误时，清理连接
            if pc:
                try:
                    await self.close_connection(client_id)
                except Exception as close_error:
                    logger.error(f"关闭连接失败 [客户端: {client_id}]: {close_error}")
    
    async def handle_answer(self, client_id, answer_data):
        """
        处理客户端发送的Answer
        
        Args:
            client_id: 客户端ID
            answer_data: Answer数据
        """
        logger.info(f"收到Answer [客户端: {client_id}]")
        
        try:
            pc = self.peer_connections.get(client_id)
            if pc:
                answer = RTCSessionDescription(sdp=answer_data["sdp"], type=answer_data["type"])
                await pc.setRemoteDescription(answer)
                logger.info(f"已设置远程描述 [客户端: {client_id}]")
            else:
                logger.warning(f"收到Answer但没有找到对应的连接 [客户端: {client_id}]")
                
        except Exception as e:
            logger.exception(f"处理Answer时出错 [客户端: {client_id}]: {e}")
    
    async def handle_ice_candidate(self, client_id: str, candidate_data: dict):
        """
        处理ICE候选者
        
        Args:
            client_id: 客户端ID
            candidate_data: ICE候选者数据
        """
        logger.info(f"收到ICE候选者原始数据 [客户端: {client_id}]: {candidate_data}")
        logger.info(f"数据类型: {type(candidate_data)}")
        
        try:
            # 检查各种可能的格式
            candidate = None
            
            # cosplay-client的格式: {"type": "ice_candidate", "payload": {...}}
            if isinstance(candidate_data, dict) and 'payload' in candidate_data:
                logger.info(f"手机Client格式 payload: {candidate_data['payload']}")
                if isinstance(candidate_data['payload'], dict):
                    # 更新candidate_data为payload内容后继续处理
                    candidate_data = candidate_data['payload']
            
            # 格式1: {"candidate": "candidate:..."}
            if isinstance(candidate_data, dict) and 'candidate' in candidate_data:
                candidate_str = candidate_data.get("candidate")
                sdp_mid = candidate_data.get('sdpMid', '0')
                sdp_mline_index = candidate_data.get('sdpMLineIndex', 0)
                logger.info(f"检测到原始candidate字符串: {candidate_str}")
                logger.info(f"sdpMid: {sdp_mid}, sdpMLineIndex: {sdp_mline_index}")
                
                # 检查candidate字符串是否有效
                if not candidate_str or not isinstance(candidate_str, str):
                    logger.warning(f"ICE candidate字符串无效 [客户端: {client_id}]")
                    return
                
                # 手动创建RTCIceCandidate对象
                from aiortc.rtcicetransport import RTCIceCandidate
                
                # 解析candidate字符串以获取必要信息
                # 格式示例: "candidate:1467250027 1 udp 2122260223 192.168.1.1 61481 typ host generation 0"
                parts = candidate_str.split()
                if len(parts) >= 8 and parts[0].startswith('candidate:'):
                    # 仅做简单处理，本应该更全面地解析
                    component = int(parts[1]) if len(parts) > 1 else 1
                    protocol = parts[2].lower() if len(parts) > 2 else "udp"
                    priority = int(parts[3]) if len(parts) > 3 else 0
                    ip = parts[4] if len(parts) > 4 else ""
                    port = int(parts[5]) if len(parts) > 5 else 0
                    # typ 后的值必须是类型
                    typ_index = parts.index('typ') if 'typ' in parts else -1
                    candidate_type = parts[typ_index + 1] if typ_index >= 0 and typ_index + 1 < len(parts) else "host"
                    
                    ice_candidate = RTCIceCandidate(
                        component=component,
                        foundation=parts[0].replace('candidate:', '') if parts[0].startswith('candidate:') else "",
                        ip=ip,
                        port=port,
                        priority=priority,
                        protocol=protocol,
                        type=candidate_type,
                        sdpMid=sdp_mid,
                        sdpMLineIndex=sdp_mline_index,
                        tcpType=None
                    )
                    
                    # 记录原始字符串以允许aiortc实现内部处理
                    ice_candidate._raw = candidate_str
                    candidate = ice_candidate
                else:
                    logger.warning(f"ICE candidate字符串格式不正确 [客户端: {client_id}]: {candidate_str}")
                    return
            
            # 格式2: 直接就是RTCIceCandidate对象
            elif isinstance(candidate_data, object) and hasattr(candidate_data, 'sdpMid') and hasattr(candidate_data, 'sdpMLineIndex'):
                candidate = candidate_data
                logger.info(f"检测到RTCIceCandidate对象: {candidate}")
            
            # 检查候选者对象是否有效
            if candidate is None:
                logger.warning(f"ICE候选者为None，无法解析 [客户端: {client_id}]")
                return
            
            logger.info(f"处理后的候选者对象类型: {type(candidate)}")
            
            # 处理客户端发送的空候选者（ICE收集完成标记）
            if hasattr(candidate, '_raw') and not candidate._raw:
                logger.info(f"收到ICE收集完成标记 [客户端: {client_id}]")
                return
                
            pc = self.peer_connections.get(client_id)
            
            # 如果连接已存在，添加ICE候选者
            if pc:
                try:
                    # 检查是否需要创建RTCIceCandidate对象
                    from aiortc.rtcicetransport import RTCIceCandidate
                    
                    if not isinstance(candidate, RTCIceCandidate):
                        # 检查必须字段
                        has_sdp_mid = isinstance(candidate, dict) and 'sdpMid' in candidate
                        has_sdp_mline_index = isinstance(candidate, dict) and 'sdpMLineIndex' in candidate
                        has_candidate = isinstance(candidate, dict) and 'candidate' in candidate
                        
                        logger.info(f"候选者字段检查 - sdpMid: {has_sdp_mid}, sdpMLineIndex: {has_sdp_mline_index}, candidate: {has_candidate}")
                        
                        # 确保候选者对象格式正确
                        if not has_candidate:
                            logger.warning(f"缺少candidate字段 [客户端: {client_id}]")
                            return
                        
                        # 创建RTCIceCandidate对象
                        sdp_mid = candidate.get('sdpMid', '0')
                        sdp_mline_index = candidate.get('sdpMLineIndex', 0)
                        candidate_str = candidate.get('candidate', '')
                        
                        logger.info(f"准备创建RTCIceCandidate - sdpMid: {sdp_mid}, sdpMLineIndex: {sdp_mline_index}, candidate: {candidate_str}")
                        
                        ice_candidate = RTCIceCandidate(
                            component=1,
                            foundation="",
                            ip="",
                            port=0,
                            priority=0,
                            protocol="",
                            type="",
                            sdpMid=sdp_mid,
                            sdpMLineIndex=sdp_mline_index,
                            tcpType=None
                        )
                        ice_candidate._raw = candidate_str
                        candidate = ice_candidate
                        
                    await pc.addIceCandidate(candidate)
                    logger.info(f"已成功添加ICE候选者 [客户端: {client_id}]")
                except AttributeError as e:
                    logger.error(f"ICE候选者格式错误的详细信息 [客户端: {client_id}]: {e}, 候选者对象: {candidate}")
                except Exception as e:
                    logger.error(f"添加ICE候选者失败的详细信息 [客户端: {client_id}]: {e}, 候选者对象: {candidate}")
            else:
                # 否则存储待处理的候选者
                if client_id not in self.pending_candidates:
                    self.pending_candidates[client_id] = []
                self.pending_candidates[client_id].append(candidate)
                logger.info(f"已存储待处理的ICE候选者 [客户端: {client_id}]")
                
        except Exception as e:
            logger.exception(f"处理ICE候选者时出错的详细信息 [客户端: {client_id}]: {e}, 原始数据: {candidate_data}")
    
    async def process_audio(self, client_id, audio_data):
        """
        处理客户端发送的音频数据
        
        Args:
            client_id: 客户端ID
            audio_data: 音频数据
        """
        # 此方法用于处理普通WebSocket连接发送的音频数据
        # WebRTC音频会直接通过MediaStreamTrack处理
        logger.debug(f"处理音频数据 [客户端: {client_id}, 大小: {len(audio_data)} 字节]")
        
        # 在这里可以将音频数据传递给音频处理管道...
        # 该实现取决于您具体的音频处理需求
    
    async def process_audio_frame(self, frame):
        """
        处理音频帧的回调函数
        
        Args:
            frame: 音频帧
        """
        # 这里实现您的音频处理逻辑
        # 例如：语音识别、音频特征提取等
        pass
    
    async def handle_connection_failure(self, client_id):
        """
        处理连接失败
        
        Args:
            client_id: 客户端ID
        """
        logger.warning(f"WebRTC连接失败 [客户端: {client_id}]")
        # 这里可以实现重连逻辑，或者通知客户端切换到备用通信方式
    
    async def close_connection(self, client_id):
        """
        关闭客户端连接
        
        Args:
            client_id: 客户端ID
        """
        # 关闭并清理对等连接
        pc = self.peer_connections.pop(client_id, None)
        if pc:
            await pc.close()
            
        # 清理关联的资源
        self.audio_processors.pop(client_id, None)
        
        # 清理数据通道
        channels_to_remove = [k for k in self.data_channels if k.startswith(f"{client_id}_")]
        for channel_key in channels_to_remove:
            self.data_channels.pop(channel_key, None)
            
        logger.info(f"已关闭客户端 {client_id} 的连接")
    
    async def close_all_connections(self):
        """关闭所有连接"""
        logger.info("关闭所有WebRTC连接...")
        
        for client_id in list(self.peer_connections.keys()):
            await self.close_connection(client_id)
