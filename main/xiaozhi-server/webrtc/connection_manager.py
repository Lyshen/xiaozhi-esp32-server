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
    
    async def handle_offer(self, client_id, offer_data, websocket=None):
        """
        处理客户端发送的Offer
        
        Args:
            client_id: 客户端ID
            offer_data: Offer数据
            websocket: WebSocket连接
        """
        logger.info(f"接收Offer [客户端: {client_id}]")
        
        # 1. 提取SDP信息
        try:
            # 处理不同格式的offer_data
            if isinstance(offer_data, dict):
                # 如果offer_data是字典，尝试获取sdp字段
                offer_sdp = offer_data.get("sdp", {})
                if isinstance(offer_sdp, dict):
                    # 如果offset_sdp是字典，直接获取type和sdp
                    type_ = offer_sdp.get("type")
                    sdp = offer_sdp.get("sdp")
                elif isinstance(offer_sdp, str):
                    # 如果offset_sdp是字符串，将其作为sdp值，type设为"offer"
                    type_ = "offer"
                    sdp = offer_sdp
                else:
                    logger.error(f"无法解析的offer_sdp格式: {type(offer_sdp)} [客户端: {client_id}]")
                    return
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
            
            # 通过信令通道发送Answer
            if websocket and websocket.open:
                await websocket.send(json.dumps(answer_data))
                logger.info(f"发送Answer [客户端: {client_id}]")
            else:
                logger.warning(f"无法发送Answer，WebSocket连接不可用 [客户端: {client_id}]")
            
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
                await pc.addIceCandidate({
                    "candidate": candidate,
                    "sdpMid": sdpMid,
                    "sdpMLineIndex": sdpMLineIndex
                })
                logger.info(f"添加ICE候选者成功 [客户端: {client_id}]")
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
    
    def associate_websocket(self, client_id, websocket):
        """
        关联WebRTC连接和WebSocket连接
        
        参数:
        client_id: 客户端 ID
        websocket: 客户端的WebSocket连接
        """
        if client_id in self.webrtc_connections:
            conn = self.webrtc_connections[client_id]
            conn.websocket = websocket
            logger.warning(f"[SERVER-CONNECTION] 已关联WebSocket和WebRTC连接: {client_id}")
            return True
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
    
    async def close_all_connections(self):
        """关闭所有连接"""
        logger.info("关闭所有WebRTC连接...")
        
        for client_id in list(self.peer_connections.keys()):
            await self.close_connection(client_id)
