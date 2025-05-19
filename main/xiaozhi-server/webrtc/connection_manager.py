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
        
        # 存储客户端的音频处理统计信息
        self.client_stats = {}  # client_id -> stats dict
        
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
                    logger.debug(f"数据通道收到文本消息 [客户端: {client_id}, 通道: {channel_id}]: {message[:100]}...")
                else:
                    logger.debug(f"数据通道收到二进制消息 [客户端: {client_id}, 通道: {channel_id}]: {len(message)} 字节")
        
        # 设置轨道回调
        @pc.on("track")
        def on_track(track):
            client_id_safe = client_id or "unknown"
            logger.info(f"WebRTC: 收到轨道 [客户端: {client_id_safe}, 类型: {track.kind}]")
            
            if track.kind == "audio":
                logger.info(f"WebRTC: 收到音频轨道 [客户端: {client_id_safe}, 格式: {track.kind}, 采样率: {track.rate if hasattr(track, 'rate') else '未知'}]")
                audio_track = track  # 获取来自对等连接的原始音频轨道
                
                # 创建处理回调
                async def frame_callback(frame):
                    try:
                        logger.info(f"WebRTC: 收到音频帧 [客户端: {client_id_safe}, 采样率: {frame.sample_rate}, 帧大小: {len(frame.to_ndarray())} 采样点]")
                        # 处理音频帧
                        await self.process_audio_frame(frame, client_id_safe)
                    except Exception as e:
                        logger.exception(f"WebRTC: 处理音频帧时出错 [客户端: {client_id_safe}]: {e}")
                
                # 创建带有回调的音频轨道处理器
                processor = AudioTrackProcessor(track, frame_callback)
                self.audio_processors[client_id_safe] = processor
                logger.info(f"WebRTC: 已创建音频处理器 [客户端: {client_id_safe}]")
            else:
                logger.info(f"WebRTC: 收到非音频轨道 [客户端: {client_id_safe}, 类型: {track.kind}]")
        
        logger.info(f"WebRTC: 音频处理器设置完成 [客户端: {client_id}]")

                
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
    
    async def _convert_audio_to_pcm(self, frame):
        """将音频帧转换为PCM格式"""
        import numpy as np
        audio_array = frame.to_ndarray()
        return audio_array.tobytes()
        
    # 添加音频包计数器和统计信息（类变量）
    _audio_packet_counters = {}  # 客户端ID -> 计数器
    _audio_bytes_counters = {}   # 客户端ID -> 字节计数
    _last_log_time = {}          # 客户端ID -> 上次日志时间
    
    async def process_audio_frame(self, frame, client_id):
        """
        处理WebRTC音频帧
        
        参数:
        frame: 音频帧
        client_id: 客户端 ID
        """
        try:
            # 更新计数器
            if client_id not in self._audio_packet_counters:
                self._audio_packet_counters[client_id] = 0
                self._audio_bytes_counters[client_id] = 0
                self._last_log_time[client_id] = 0
                
            self._audio_packet_counters[client_id] += 1
            counter = self._audio_packet_counters[client_id]
            
            # 添加明确的日志 - 记录开始处理音频，使用明确的标记便于在Docker日志中查找
            logger.warning(f"[SERVER-AUDIO] 接收音频包 #{counter} 来自客户端 {client_id}, 时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
            
            # 1. 将音频帧转换为PCM格式 (原VAD链路需要的格式)
            audio_array = await self._convert_audio_to_pcm(frame)
            self._audio_bytes_counters[client_id] += len(audio_array)
            logger.warning(f"[SERVER-AUDIO] 音频转换完成，数据包 #{counter}，大小: {len(audio_array)} 字节，累计: {self._audio_bytes_counters[client_id]} 字节")
            
            # 2. 创建简单的连接对象，用于传递给VAD处理链路
            class WebRTCConnection:
                def __init__(self):
                    # 基本识别属性
                    self.client_id = client_id
                    self.headers = {"device-id": client_id}
                    self.session_id = f"webrtc_{client_id}"
                    
                    # VAD相关属性 - process_audio_internal所需
                    self.client_audio_buffer = bytearray()
                    self.client_listen_mode = "auto"
                    self.client_have_voice = False
                    self.client_voice_stop = False
                    self.client_abort = False
                    self.client_no_voice_last_time = 0.0
                    
                    # ASR相关属性 - process_audio_internal所需
                    self.asr_server_receive = True  # 确保设置这个属性以避免AttributeError
                    self.asr_audio = []  # 用于存储音频数据
                    
                    # 其他属性
                    self.use_webrtc = True
                    self.need_bind = False
                    self.max_output_size = 0
                    self.close_after_chat = False
                    
                    # 明确记录已初始化ASR相关属性，用于调试
                    logger.warning(f"[SERVER-AUDIO] WebRTCConnection对象创建，客户端ID: {client_id}, asr_server_receive已设置为{self.asr_server_receive}")
                    
                    # 创建一个模拟的VAD对象
                    from unittest.mock import MagicMock
                    
                    class VADHelper:
                        def is_vad(self, conn, audio):
                            logger.info(f"WebRTC: VAD模拟判断音频，长度: {len(audio)} 字节")
                            # 始终返回有声音，确保音频能进入处理链路
                            return True
                    
                    self.vad = VADHelper()
                    
                    # 创建一个模拟的ASR对象
                    class ASRHelper:
                        async def speech_to_text(self, audio_data, session_id):
                            logger.info(f"WebRTC: ASR模拟处理音频，长度: {len(audio_data)} 段")
                            return "WebRTC音频测试成功", None
                    
                    self.asr = ASRHelper()
                    logger.info(f"WebRTC: 创建连接对象完成，客户端ID: {client_id}")
                    
                def should_replace_opus(self):
                    return True
                    
                def reset_vad_states(self):
                    logger.info(f"WebRTC: 重置VAD状态")
                    self.client_have_voice = False
                    self.client_voice_stop = False
                    
                async def chat(self, text):
                    logger.info(f"WebRTC: 模拟聊天调用, 文本: {text}")
                    return f"WebRTC测试回应: {text}"
                    
                async def chat_with_function_calling(self, text):
                    logger.info(f"WebRTC: 模拟函数调用聊天, 文本: {text}")
                    return f"WebRTC测试函数调用回应: {text}"
            
            # 3. 创建连接对象
            conn = WebRTCConnection()
            
            # 4. 将音频数据添加到缓冲区
            conn.client_audio_buffer.extend(audio_array)
            logger.warning(f"[SERVER-AUDIO] 音频数据已添加到缓冲区，客户端: {client_id}, 数据包 #{self._audio_packet_counters[client_id]}, 当前缓冲区大小: {len(conn.client_audio_buffer)} 字节")
            
            # 5. 引入process_audio_internal函数
            try:
                from main.xiaozhi_server.core.handle.receiveAudioHandle import process_audio_internal
                logger.warning(f"[SERVER-AUDIO] 成功导入原有VAD处理链路 (主路径)")
            except ImportError:
                # 备选导入路径
                try:
                    from core.handle.receiveAudioHandle import process_audio_internal
                    logger.warning(f"[SERVER-AUDIO] 成功从备选路径导入原有VAD处理链路")
                except ImportError as e:
                    logger.error(f"[SERVER-AUDIO] 无法导入VAD处理链路: {str(e)}")
                    return
            
            # 6. 将音频数据传递到VAD处理链路
            logger.warning(f"[SERVER-AUDIO] 正在调用原有VAD处理链路，数据包 #{self._audio_packet_counters[client_id]}，传递音频长度: {len(audio_array)} 字节")
            result = await process_audio_internal(conn, audio_array)
            logger.warning(f"[SERVER-AUDIO] VAD处理链路已完成，数据包 #{self._audio_packet_counters[client_id]}，结果: {result}")
            
            # 7. 更新统计信息
            client_info = self.client_stats.get(client_id, {'frames_processed': 0, 'bytes_processed': 0})
            client_info['frames_processed'] = client_info.get('frames_processed', 0) + 1
            client_info['bytes_processed'] = client_info.get('bytes_processed', 0) + len(audio_array)
            self.client_stats[client_id] = client_info
            
            # 定期输出统计信息
            if client_info['frames_processed'] % 100 == 0:
                logger.info(f"WebRTC已处理 {client_info['frames_processed']} 帧音频 [客户端: {client_id}]")
            
            return result
        
        except Exception as e:
            logger.error(f"[SERVER-AUDIO-ERROR] 处理音频帧时出错: {str(e)}")
            logger.error(f"[SERVER-AUDIO-ERROR] 错误详情: {e.__class__.__name__}: {str(e)}")
            import traceback
            logger.error(f"[SERVER-AUDIO-ERROR] 堆栈跟踪: {traceback.format_exc()}")
            return None
    
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
