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
        
        # 会话ID映射表 - 将WebRTC会话ID映射到客户端ID
        self.session_map = {}  # session_id -> client_id
        
        # 客户端ID映射表 - 将不同类型的客户端ID进行映射
        self.client_id_map = {}  # p2p_client_id (UUID) -> real_client_id (device-id)
        
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
            if pc.iceConnectionState == "checking":
                logger.info(f"WebRTC: ICE连接正在检查候选者 [客户端: {client_id}]")
            elif pc.iceConnectionState == "connected":
                logger.info(f"WebRTC: ICE连接已成功建立 [客户端: {client_id}]")
                # 获取选中的ICE候选者信息
                try:
                    stats = await pc.getStats()
                    for stat in stats.values():
                        if stat.type == "candidate-pair" and stat.state == "succeeded":
                            logger.info(f"WebRTC: P2P连接详情 [客户端: {client_id}] - 本地候选者类型: {stat.localCandidateType}, 远程候选者类型: {stat.remoteCandidateType}, 传输协议: {stat.protocol}")
                except Exception as e:
                    logger.error(f"WebRTC: 获取ICE统计信息失败 [客户端: {client_id}]: {e}")
            elif pc.iceConnectionState == "completed":
                logger.info(f"WebRTC: ICE连接已完成并稳定 [客户端: {client_id}]")
                # 记录连接完成时的详细信息
                try:
                    stats = await pc.getStats()
                    for stat in stats.values():
                        if stat.type == "transport":
                            logger.info(f"WebRTC: P2P传输详情 [客户端: {client_id}] - 字节已发送: {stat.bytesSent}, 字节已接收: {stat.bytesReceived}, RTT: {stat.currentRoundTripTime if hasattr(stat, 'currentRoundTripTime') else 'N/A'}ms")
                except Exception as e:
                    logger.error(f"WebRTC: 获取传输统计信息失败 [客户端: {client_id}]: {e}")
            elif pc.iceConnectionState == "failed":
                logger.info(f"WebRTC: ICE连接失败 [客户端: {client_id}]")
                await self.handle_connection_failure(client_id)
        
        # 设置数据通道回调
        @pc.on("datachannel")
        def on_datachannel(channel):
            channel_id = channel.label
            logger.info(f"数据通道已创建 [客户端: {client_id}, 通道: {channel_id}]")
            self.data_channels[f"{client_id}_{channel_id}"] = channel
            
            # 初始化消息计数器
            msg_count = 0
            json_bytes = 0
            bin_bytes = 0
            last_log_time = time.time()
            
            # 音频数据缓存
            audio_buffer = bytearray()  # 缓存音频数据
            is_opus_format = False  # 音频格式标记
            
            @channel.on("message")
            def on_message(message):
                nonlocal msg_count, json_bytes, bin_bytes, last_log_time, audio_buffer, is_opus_format
                msg_count += 1
                current_time = time.time()
                
                # 处理JSON字符串消息
                if isinstance(message, str):
                    try:
                        data = json.loads(message)
                        msg_size = len(message)
                        json_bytes += msg_size
                        
                        # 音频数据包特殊处理
                        if 'id' in data and 'data' in data and 'sampleRate' in data:
                            
                            # 检查音频格式
                            if 'format' in data:
                                format_type = data['format'].lower()
                                if format_type == 'opus':
                                    is_opus_format = True
                                    if msg_count == 1:
                                        logger.info(f"[DATACHANNEL] 音频格式检测: Opus [客户端: {client_id}]")
                                else:
                                    if msg_count == 1:
                                        logger.info(f"[DATACHANNEL] 音频格式检测: {format_type} [客户端: {client_id}]")
                            # 使用头部特征判断是否为Opus
                            elif msg_count == 1 and isinstance(data['data'], list) and len(data['data']) > 10:
                                # 试图检测这是否是OPUS签名特征
                                opus_header_signature = [79, 112, 117, 115, 72, 101, 97, 100]  # "OpusHead"的ASCII码
                                if all(data['data'][i] == opus_header_signature[i] for i in range(min(8, len(data['data'])))):
                                    is_opus_format = True
                                    logger.info(f"[DATACHANNEL] 通过特征侦测到Opus格式 [客户端: {client_id}]")
                            
                            # 将音频数据添加到缓冲区
                            try:
                                # 将JSON数组转为二进制数据
                                audio_data = bytearray()
                                for sample in data['data']:
                                    # 直接将数字转为字节
                                    if isinstance(sample, int):
                                        audio_data.append(sample & 0xFF)
                                    else:
                                        # 强制转换为整数
                                        audio_data.append(int(float(sample)) & 0xFF)
                                
                                # 累积到缓冲区
                                audio_buffer.extend(audio_data)
                            except Exception as e:
                                logger.error(f"[DATACHANNEL] 音频数据转换失败 [客户端: {client_id}]: {e}")
                            
                            # 音频数据包只每100个输出一次日志
                            if msg_count % 100 == 1 or (current_time - last_log_time) > 10:
                                logger.info(f"[DATACHANNEL] 音频数据包统计 [客户端: {client_id}]: "
                                          f"计数: {msg_count}, 音频包ID: {data['id']}, "
                                          f"采样率: {data['sampleRate']}Hz, "
                                          f"格式: {'Opus' if is_opus_format else '未知'}, "
                                          f"缓冲区大小: {len(audio_buffer)} 字节")
                                last_log_time = current_time
                        # 控制命令始终输出日志
                        elif 'command' in data:
                            logger.info(f"[DATACHANNEL] 收到控制命令 [客户端: {client_id}]: {data['command']}")
                            
                            # 处理停止录音命令（按钮释放）
                            if data['command'] == 'stop_recording' or data['command'] == 'stop':
                                logger.info(f"[DATACHANNEL] 检测到停止录音命令 [客户端: {client_id}]")
                                
                                # 获取真实客户端ID
                                real_id = self.get_real_client_id(client_id)
                                if real_id != client_id:
                                    logger.info(f"[DATACHANNEL] 客户端ID已映射 [原始ID: {client_id}, 真实ID: {real_id}]")
                                
                                # 查找真实客户端ID的WebRTC连接
                                if real_id in self.webrtc_connections:
                                    webrtc_conn = self.webrtc_connections[real_id]
                                    # 标记按钮释放状态
                                    webrtc_conn.client_voice_stop = True
                                    webrtc_conn.client_voice_stop_requested = True
                                    logger.info(f"[DATACHANNEL] 已设置按钮释放状态 [客户端: {real_id}]")
                                elif client_id in self.webrtc_connections:
                                    # 如果映射后找不到，尝试使用原始ID
                                    webrtc_conn = self.webrtc_connections[client_id]
                                    webrtc_conn.client_voice_stop = True
                                    webrtc_conn.client_voice_stop_requested = True
                                    logger.info(f"[DATACHANNEL] 使用原始ID设置按钮释放状态 [客户端: {client_id}]")
                                    # 添加映射关系，确保后续操作一致性
                                    self.client_id_map[client_id] = client_id
                                    
                                    # 将缓存的音频数据传给VAD/ASR处理
                                    if len(audio_buffer) > 0:
                                        logger.info(f"[DATACHANNEL] 开始处理缓存的音频数据 [客户端: {client_id}, 大小: {len(audio_buffer)} 字节]")
                                        # 将缓存的数据复制到连接对象的缓冲区
                                        webrtc_conn.client_audio_buffer.extend(audio_buffer)
                                        # 触发VAD/ASR处理
                                        asyncio.create_task(self._process_buffered_audio(client_id, bytes(audio_buffer)))
                                        # 清空缓冲区
                                        audio_buffer = bytearray()
                                else:
                                    logger.warning(f"[DATACHANNEL] 找不到客户端的WebRTC连接对象 [客户端: {client_id}]")
                        # 其他普通JSON消息
                        else:
                            logger.info(f"[DATACHANNEL] 收到JSON消息 [客户端: {client_id}]: {data}")
                    except json.JSONDecodeError:
                        # 非JSON格式字符串只每100个输出一次
                        if msg_count % 100 == 1:
                            logger.info(f"[DATACHANNEL] 收到非JSON字符串 [客户端: {client_id}]: {message[:50]}...")
                # 处理二进制消息
                else:
                    msg_size = len(message)
                    bin_bytes += msg_size
                    
                    # 二进制消息只每100个输出一次日志
                    if msg_count % 100 == 1 or (current_time - last_log_time) > 10:
                        logger.info(f"[DATACHANNEL] 二进制消息统计 [客户端: {client_id}]: "
                                  f"计数: {msg_count}, 当前大小: {msg_size} 字节, "
                                  f"累计二进制字节数: {bin_bytes}")
                        last_log_time = current_time
        
        # 设置音频/视频轨道回调
        @pc.on("track")
        async def on_track(track):
            logger.info(f"on_track {track.kind}")
            if track.kind == "audio":
                # 检查是否有会话ID关联
                session_ids = [sid for sid, cid in self.session_map.items() if cid == client_id]
                if session_ids:
                    logger.info(f"收到音频轨道 [客户端: {client_id}, 会话ID: {session_ids[0]}]")
                else:
                    logger.info(f"收到音频轨道 [客户端: {client_id}]")
                
                # 记录轨道的详细信息
                logger.info(f"[SERVER-AUDIO-TRACK] 轨道详情 [客户端: {client_id}]")
                logger.info(f"[SERVER-AUDIO-TRACK] 类型: {track.kind}")
                logger.info(f"[SERVER-AUDIO-TRACK] ID: {track.id if hasattr(track, 'id') else 'unknown'}")
                
                # 尝试获取编解码器信息
                try:
                    # 检查当前会话描述中的codec信息
                    if pc.remoteDescription:
                        sdp = pc.remoteDescription.sdp
                        import re
                        # 提取音频编解码器信息
                        codec_lines = re.findall(r'a=rtpmap:\d+ ([^\r\n]+)', sdp)
                        opus_codecs = [c for c in codec_lines if 'opus' in c.lower()]
                        if opus_codecs:
                            logger.info(f"[SERVER-AUDIO-CODEC] 检测到Opus编解码器: {opus_codecs}")
                        else:
                            logger.info(f"[SERVER-AUDIO-CODEC] 所有编解码器: {codec_lines}")
                        
                        # 提取采样率信息
                        sample_rate_matches = re.findall(r'opus/([0-9]+)/', sdp)
                        if sample_rate_matches:
                            logger.info(f"[SERVER-AUDIO-CODEC] Opus采样率: {sample_rate_matches[0]}Hz")
                except Exception as e:
                    logger.error(f"[SERVER-AUDIO-CODEC] 获取编解码器信息失败: {e}")
                    import traceback
                    logger.error(f"[SERVER-AUDIO-CODEC] 堆栈跟踪: {traceback.format_exc()}")
                
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
        client_id: 客户端 ID
        offer_data: Offer数据
        websocket: WebSocket连接对象（可选）
        """
        try:
            logger.info(f"处理Offer [客户端初始 ID: {client_id}]")
            
            # 从客户端数据中提取真正的客户端ID
            real_client_id = None
            
            # 1. 先尝试从WebSocket的headers中获取device-id
            device_id_from_header = None
            if websocket and hasattr(websocket, 'request') and hasattr(websocket.request, 'headers'):
                headers = dict(websocket.request.headers)
                if 'device-id' in headers:
                    device_id_from_header = headers['device-id']
                    logger.info(f"从WebSocket headers中提取到device-id: {device_id_from_header}")
            
            # 2. 从Offer数据中寻找客户端ID
            if isinstance(offer_data, dict):
                # 直接检查是否有client_id字段
                if 'client_id' in offer_data:
                    real_client_id = offer_data['client_id']
                    logger.info(f"从Offer数据中提取到client_id: {real_client_id}")
                    
                # 检查payload内部
                elif 'payload' in offer_data and isinstance(offer_data['payload'], dict):
                    if 'client_id' in offer_data['payload']:
                        real_client_id = offer_data['payload']['client_id']
                        logger.info(f"从Offer payload中提取到client_id: {real_client_id}")
                        
                # 检查device-id字段
                elif 'device-id' in offer_data:
                    real_client_id = offer_data['device-id']
                    logger.info(f"从Offer数据中提取到device-id: {real_client_id}")
                    
            # 3. 如果从 headers 和 offer 中都找到了ID，优先使用 headers 中的
            if device_id_from_header:
                if real_client_id and real_client_id != device_id_from_header:
                    logger.info(f"客户端ID不匹配，使用WebSocket headers中的ID [原始P2P ID: {client_id}, Offer ID: {real_client_id}, WebSocket ID: {device_id_from_header}]")
                    # 使用WebSocket headers中的device-id作为最终ID
                    real_client_id = device_id_from_header
            
            # 如果找到真实客户端ID，存储映射关系并替换初始的client_id
            if real_client_id and real_client_id != client_id:
                logger.info(f"客户端ID不匹配，用最终确定的ID替换 [原始P2P ID: {client_id}, 最终ID: {real_client_id}]")
                # 保存映射关系，从原始P2P ID映射到最终ID
                self.client_id_map[client_id] = real_client_id
                # 替换当前处理中使用的ID
                client_id = real_client_id
            
            # 尝试从 SDP 中提取会话ID
            sdp = offer_data.get("sdp")
            session_id = self.extract_session_id_from_sdp(sdp)
            if session_id:
                logger.info(f"从Offer SDP中提取到会话ID: {session_id} [客户端: {client_id}]")
                # 建立会话ID和客户端ID的映射关系
                self.session_map[session_id] = client_id
                
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
            # 修改Answer格式，使其符合WebRTC标准格式
            answer_data = {
                "type": "answer",
                "payload": {
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
        
    def extract_session_id_from_sdp(self, sdp):
        """
        从SDP中提取会话ID
        
        Args:
            sdp: SDP字符串
            
        Returns:
            str: 提取到的会话ID，如果没有则返回None
        """
        if not sdp:
            return None
            
        # 寻找自定义的session-id属性
        lines = sdp.split("\n")
        for line in lines:
            if line.startswith("a=session-id:"):
                session_id = line.split(":", 1)[1].strip()
                logger.info(f"从SDP中提取到会话ID: {session_id}")
                return session_id
                
        return None
        
    def get_client_id_by_session(self, session_id):
        """
        通过会话ID查找对应的客户端ID
        
        Args:
            session_id: 会话ID
            
        Returns:
            str: 客户端ID，如果没有找到则返回None
        """
        return self.session_map.get(session_id)
    
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
        # 初始化计数器
        if client_id not in self.audio_packet_counters:
            self.audio_packet_counters[client_id] = 0
            self.audio_bytes_counters[client_id] = 0
            self.last_log_time[client_id] = time.time()
        
        # 增加包计数器
        self.audio_packet_counters[client_id] += 1
        frame_counter = self.audio_packet_counters[client_id]
        
        # 计算帧大小
        frame_size = 0
        try:
            if hasattr(frame, 'planes') and frame.planes:
                # 使用正确的方法获取AudioPlane的大小
                if hasattr(frame.planes[0], 'buffer_size'):
                    frame_size = frame.planes[0].buffer_size
                elif hasattr(frame.planes[0], 'line_size'):
                    frame_size = frame.planes[0].line_size
                elif hasattr(frame, 'samples') and hasattr(frame, 'channels'):
                    # 根据样本数和通道数计算帧大小
                    bytes_per_sample = 2  # 假设16位样本 (2字节)
                    frame_size = frame.samples * frame.channels * bytes_per_sample
            elif hasattr(frame, 'to_ndarray'):
                try:
                    frame_size = len(frame.to_ndarray().tobytes())
                except Exception as e:
                    logger.warning(f"[SERVER-AUDIO] 无法使用to_ndarray获取帧大小: {e}")
        except Exception as e:
            logger.warning(f"[SERVER-AUDIO] 计算帧大小时出错: {e}")
        
        # 累计字节数
        self.audio_bytes_counters[client_id] += frame_size
        
        # 前10帧都详细记录，之后每10帧记录一次
        if frame_counter <= 10 or frame_counter % 10 == 0:
            format_name = frame.format.name if hasattr(frame, 'format') and frame.format else 'unknown'
            sample_rate = frame.sample_rate if hasattr(frame, 'sample_rate') else 'unknown'
            channels = getattr(frame, 'channels', '?')
            samples = getattr(frame, 'samples', '?')
            pts = getattr(frame, 'pts', 0)
            
            # 为前10帧使用更明显的标记
            log_prefix = "[SERVER-AUDIO-FRAME]" if frame_counter <= 10 else "[P2P-RX-DEBUG]"
            
            logger.info(f"{log_prefix} 接收到音频帧 #{frame_counter} [客户端: {client_id}], "
                    f"格式: {format_name}, 采样率: {sample_rate}Hz, "
                    f"通道数: {channels}, 样本数: {samples}, PTS: {pts}, "
                    f"大小: {frame_size} 字节, 累计: {self.audio_bytes_counters[client_id]} 字节")
            
            # 对第一帧进行额外的处理和检查
            if frame_counter == 1:
                logger.info(f"[SERVER-AUDIO-FIRST-FRAME] 首个音频帧详情 [客户端: {client_id}]:")
                
                # 尝试输出更多详细信息
                for attr_name in dir(frame):
                    if not attr_name.startswith('_') and not callable(getattr(frame, attr_name, None)):
                        try:
                            attr_value = getattr(frame, attr_name)
                            logger.info(f"[SERVER-AUDIO-FIRST-FRAME] {attr_name} = {attr_value}")
                        except Exception:
                            pass
        
        # 创建AudioFrameHandler实例（如果尚未创建）
        if not hasattr(self, 'audio_frame_handler'):
            from .modules.audio_frame_handler import AudioFrameHandler
            self.audio_frame_handler = AudioFrameHandler()
        
        # 使用AudioFrameHandler处理音频帧
        try:
            # 使用帧处理器处理音频帧
            await self.audio_frame_handler.process_audio_frame(frame, client_id, self.webrtc_connections)
        except Exception as e:
            logger.error(f"[SERVER-AUDIO-ERROR] 处理音频帧时发生错误: {e}")
            logger.error(f"[SERVER-AUDIO-ERROR] 堆栈跟踪: {traceback.format_exc()}")
    
    async def handle_connection_failure(self, client_id):
        """
        处理连接失败
        
        Args:
            client_id: 客户端ID
        """
        await self.close_connection(client_id)
        logger.warning(f"连接失败处理完成 [客户端: {client_id}]")
        
    async def _process_buffered_audio(self, client_id, audio_bytes):
        """
        处理缓存的音频数据
        
        参数:
        client_id: 客户端 ID
        audio_bytes: 音频数据字节
        """
        if not audio_bytes or len(audio_bytes) == 0:
            logger.warning(f"[AUDIOBUFFER] 缓存的音频数据为空 [客户端: {client_id}]")
            return
            
        logger.info(f"[AUDIOBUFFER] 开始处理缓存的音频数据 [客户端: {client_id}, 大小: {len(audio_bytes)} 字节]")
        
        try:
            # 获取WebRTC连接对象
            if client_id in self.webrtc_connections:
                webrtc_conn = self.webrtc_connections[client_id]
                
                # 检测是否为Opus格式
                is_opus = False
                if len(audio_bytes) >= 8:
                    # 检查Opus头部特征
                    opus_signature = b'OpusHead'
                    if audio_bytes[:8] == opus_signature:
                        is_opus = True
                        logger.info(f"[AUDIOBUFFER] 检测到Opus格式数据 [客户端: {client_id}]")
                
                # 如果是Opus格式，尝试解码（实际环境中可能需要调用opus解码器）
                if is_opus:
                    logger.info(f"[AUDIOBUFFER] 检测到Opus格式，使用原始数据 [客户端: {client_id}]")
                    # 注意：这里只检测格式，实际解码需要额外实现
                
                # 调用WebRTC连接对象的内部音频处理方法
                if hasattr(webrtc_conn, 'process_audio_internal'):
                    await webrtc_conn.process_audio_internal(audio_bytes)
                    logger.info(f"[AUDIOBUFFER] 已将缓存音频数据传递给VAD/ASR处理 [客户端: {client_id}]")
                else:
                    logger.warning(f"[AUDIOBUFFER] WebRTC连接对象缺少process_audio_internal方法 [客户端: {client_id}]")
            else:
                logger.warning(f"[AUDIOBUFFER] 找不到客户端的WebRTC连接对象 [客户端: {client_id}]")
        except Exception as e:
            logger.error(f"[AUDIOBUFFER] 处理缓存音频数据时出错 [客户端: {client_id}]: {e}")
            import traceback
            logger.error(traceback.format_exc())
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
        
    def get_real_client_id(self, client_id):
        """
        获取客户端的真实客户端ID
        
        参数:
        client_id: 原始客户端ID（可能是P2P连接生成的UUID）
        
        返回:
        真实客户端ID（通常是device-id）
        """
        # 如果在映射表中存在，返回映射的真实客户端ID
        if client_id in self.client_id_map:
            mapped_id = self.client_id_map[client_id]
            logger.debug(f"使用映射关系转换客户端ID [原始: {client_id}, 真实: {mapped_id}]")
            return mapped_id
            
        # 如果在会话map中存在，使用会话映射
        for session_id, mapped_client_id in self.session_map.items():
            if mapped_client_id == client_id:
                # 检查这个映射的客户端ID是否已经有进一步的映射
                if mapped_client_id in self.client_id_map:
                    final_id = self.client_id_map[mapped_client_id]
                    logger.debug(f"通过会话映射关系转换客户端ID [原始: {client_id}, 会话ID: {session_id}, 真实: {final_id}]")
                    return final_id
        
        # 如果没有映射关系，返回原始客户端ID
        return client_id
            
    async def close_all_connections(self):
        """关闭所有连接"""
        logger.info("关闭所有WebRTC连接...")
        
        for client_id in list(self.peer_connections.keys()):
            await self.close_connection(client_id)
