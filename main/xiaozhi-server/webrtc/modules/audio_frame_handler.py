#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
音频帧处理模块，负责处理WebRTC音频帧的接收、分析和转发
"""

import asyncio
import copy
import json
import logging
import time
import traceback
from concurrent.futures import ThreadPoolExecutor

import av
import builtins
import numpy as np

from config.logger import setup_logging
# 导入PCM转Opus编码器
from webrtc.modules.audio_encoder import encode_pcm_to_opus

logger = setup_logging()

class AudioFrameHandler:
    """处理WebRTC音频帧的类"""

    def __init__(self):
        # 初始化统计数据结构
        self.audio_packet_counters = {}
        self.audio_bytes_counters = {}
        self.last_log_time = {}
        self.client_stats = {}
    
    async def _process_audio_for_asr(self, conn, client_id):
        """
        处理音频数据进行ASR识别
        
        Args:
            conn: WebRTC连接对象
            client_id: 客户端ID
            
        Returns:
            str: 识别结果文本，如果失败则返回空字符串
        """
        logger.warning(f"[SERVER-AUDIO] 开始处理整合的音频段，总共 {len(conn.asr_audio)} 段，准备调用ASR处理")
        
        # 暂停接收新音频
        conn.asr_server_receive = False
        
        try:
            # 提取音频数据，确保所有数据都是Opus格式
            opus_audio_data = []
            format_stats = {"opus": 0, "opus-converted": 0, "pcm": 0, "other": 0}
            
            # 收集和整理音频数据
            for item in conn.asr_audio:
                if isinstance(item, dict) and 'data' in item:
                    data_format = item.get('format', 'unknown')
                    if data_format in ['opus', 'opus-converted']:
                        opus_audio_data.append(item['data'])
                        format_stats[data_format] += 1
                    elif data_format == 'pcm':
                        format_stats['pcm'] += 1
                        # PCM数据已在前面转换为Opus，跳过
                        continue
                    else:
                        format_stats['other'] += 1
                        opus_audio_data.append(item['data'])
                elif item is not None:
                    # 兼容旧版存储格式
                    opus_audio_data.append(item)
                    format_stats['other'] += 1
            
            # 记录音频数据统计
            logger.info(f"[SERVER-AUDIO] ASR数据统计: 原始Opus: {format_stats['opus']}段, "
                       f"转换Opus: {format_stats['opus-converted']}段, PCM: {format_stats['pcm']}段, "
                       f"其他: {format_stats['other']}段")
            
            # 如果没有音频数据，直接返回
            if not opus_audio_data:
                logger.warning("[SERVER-AUDIO] 无效的音频数据，取消ASR处理")
                return ""
                
            # 调用ASR处理
            logger.info(f"[SERVER-AUDIO] 总共有效音频数据: {len(opus_audio_data)}段")
            text, extra_info = await conn.asr.speech_to_text(opus_audio_data, conn.session_id)
            logger.warning(f"[SERVER-AUDIO] ASR识别结果: '{text}'")
            
            # 清空音频缓冲区并重置状态
            conn.asr_audio.clear()
            if hasattr(conn, 'reset_vad_states'):
                conn.reset_vad_states()
            else:
                conn.client_have_voice = False
                conn.client_voice_stop = False
                if hasattr(conn, 'client_voice_stop_requested'):
                    conn.client_voice_stop_requested = False
            
            # 恢复接收新音频
            conn.asr_server_receive = True
            logger.warning("[SERVER-AUDIO] ASR处理完成，已重置状态，恢复接收音频")
            logger.warning(f"[SERVER-AUDIO] VAD状态已重置: have_voice={conn.client_have_voice}, voice_stop={conn.client_voice_stop}, stop_requested={getattr(conn, 'client_voice_stop_requested', False)}")
            
            # 如果识别出文本，处理用户意图
            if text and len(text.strip()) > 0:
                try:
                    # 导入必要的模块
                    try:
                        from core.handle.sendAudioHandle import send_stt_message
                        from core.handle.intentHandler import handle_user_intent
                    except ImportError:
                        from main.xiaozhi_server.core.handle.sendAudioHandle import send_stt_message
                        from main.xiaozhi_server.core.handle.intentHandler import handle_user_intent
                        
                    # 处理用户意图
                    if conn.websocket:
                        intent_handled = await handle_user_intent(conn, text)
                        if not intent_handled:
                            # 没有特殊意图，继续常规聊天
                            await send_stt_message(conn, text)
                            if hasattr(conn, 'use_function_call_mode') and conn.use_function_call_mode:
                                conn.executor.submit(conn.chat_with_function_calling, text)
                            else:
                                conn.executor.submit(conn.chat, text)
                except Exception as e:
                    logger.error(f"[SERVER-AUDIO-ERROR] 处理ASR结果时发生错误: {e}")
                    logger.error(f"[SERVER-AUDIO-ERROR] 堆栈跟踪: {traceback.format_exc()}")
            
            return text
            
        except Exception as e:
            logger.error(f"[SERVER-AUDIO-ERROR] ASR处理失败: {e}")
            logger.error(f"[SERVER-AUDIO-ERROR] 错误详情: {traceback.format_exc()}")
            
            # 出错时也清空音频缓冲区并恢复状态
            conn.asr_audio.clear()
            conn.client_have_voice = False
            conn.client_voice_stop = False
            conn.asr_server_receive = True
            
            return ""
    
    async def convert_audio_to_pcm(self, frame):
        """将音频帧转换为PCM格式"""
        try:
            # 检查frame是否为None
            if frame is None:
                logger.warning("[AUDIO-DEBUG] 音频帧为None，无法处理")
                return b''
                
            # 记录音频帧的详细信息
            try:
                if hasattr(frame, 'format') and hasattr(frame, 'sample_rate') and hasattr(frame, 'layout'):
                    # 安全地获取to_ndarray的长度
                    samples_count = "未知"
                    try:
                        if hasattr(frame, 'to_ndarray'):
                            arr = frame.to_ndarray()
                            if arr is not None and hasattr(arr, 'size'):
                                samples_count = arr.size
                    except Exception:
                        pass
                        
                    logger.info(f"[AUDIO-DEBUG] 音频帧信息 - 格式: {frame.format.name}, 采样率: {frame.sample_rate}, 通道: {frame.layout.name}, 样本数: {samples_count}")
            except Exception as e:
                logger.warning(f"[AUDIO-DEBUG] 无法获取音频帧详细信息: {e}")
            
            # 检查是否是opus格式
            if hasattr(frame, 'format') and hasattr(frame.format, 'name') and frame.format.name.lower() == 'opus':
                logger.info(f"[AUDIO-DEBUG] 检测到Opus格式，提取原始数据")
                # 尝试保留原始的Opus编码数据
                try:
                    if hasattr(frame, 'planes') and frame.planes:
                        # 直接使用原始Opus编码数据
                        opus_data = bytes(frame.planes[0])
                        logger.info(f"[AUDIO-DEBUG] 成功提取Opus编码数据，长度: {len(opus_data)} 字节")
                        return opus_data
                except Exception as opus_err:
                    logger.warning(f"[AUDIO-DEBUG] 提取Opus数据失败: {opus_err}，回退到PCM解码")
                    # 如果提取失败，回退到标准PCM转换
            
            # 尝试不同方法提取PCM数据
            # 方法1: 使用to_ndarray方法
            try:
                if hasattr(frame, 'to_ndarray'):
                    audio_array = frame.to_ndarray()
                    if audio_array is not None and hasattr(audio_array, 'size') and audio_array.size > 0:
                        pcm_data = audio_array.flatten().tobytes()
                        logger.info(f"[AUDIO-DEBUG] 方法1: PCM转换完成，输出长度: {len(pcm_data)} 字节，前10字节: {pcm_data[:10] if len(pcm_data) >= 10 else pcm_data}")
                        return pcm_data
                    else:
                        logger.warning(f"[AUDIO-DEBUG] 方法1: 音频数组为空或无效")
            except Exception as e:
                logger.warning(f"[AUDIO-DEBUG] 方法1提取PCM失败: {e}")
                
            # 方法2: 尝试从planes直接提取原始字节
            try:
                if hasattr(frame, 'planes') and frame.planes and len(frame.planes) > 0:
                    raw_data = bytes(frame.planes[0])
                    if raw_data:
                        logger.info(f"[AUDIO-DEBUG] 方法2: 从planes提取PCM数据成功，长度: {len(raw_data)} 字节")
                        return raw_data
                    else:
                        logger.warning(f"[AUDIO-DEBUG] 方法2: planes中没有有效数据")
            except Exception as e:
                logger.warning(f"[AUDIO-DEBUG] 方法2提取PCM失败: {e}")
                
            # 如果所有方法都失败
            logger.warning(f"[AUDIO-DEBUG] 所有PCM提取方法都失败")
            return b''
        except Exception as e:
            logger.error(f"[AUDIO-DEBUG] 音频转换错误: {str(e)}")
            logger.error(f"[AUDIO-DEBUG] 错误详情: {e.__class__.__name__}: {str(e)}")
            logger.error(f"[AUDIO-DEBUG] 堆栈跟踪: {traceback.format_exc()}")
            # 返回空数据
            return b''
        
    async def process_audio_frame(self, frame, client_id, webrtc_connections):
        """
        处理WebRTC音频帧
        
        参数:
        frame: 音频帧
        client_id: 客户端 ID
        webrtc_connections: WebRTC连接字典
        """
        try:
            # 初始化或获取计数器
            if client_id not in self.audio_packet_counters:
                self.audio_packet_counters[client_id] = 0
                self.audio_bytes_counters[client_id] = 0
                self.last_log_time[client_id] = 0
            
            # 增加帧计数
            self.audio_packet_counters[client_id] += 1
            counter = self.audio_packet_counters[client_id]
            
            # 每个音频帧都记录日志，增强了日志输出
            pcm_data_size = 0
            frame_format = "unknown"
            sample_rate = "unknown"
            
            # 获取帧数据信息
            if hasattr(frame, 'format') and frame.format:
                frame_format = frame.format.name
            if hasattr(frame, 'sample_rate'):
                sample_rate = frame.sample_rate
                
            # 转换音频数据为PCM和计算大小
            try:
                audio_array = None
                if hasattr(frame, 'to_ndarray'):
                    audio_array = frame.to_ndarray()
                    pcm_data_size = len(audio_array.tobytes()) if audio_array.size > 0 else 0
                elif hasattr(frame, 'planes') and frame.planes:
                    pcm_data_size = len(frame.planes[0])
            except Exception as e:
                logger.error(f"[P2P-RX-ERROR] 转换音频数据出错: {e}")
                
            # 累计已收到的字节数
            self.audio_bytes_counters[client_id] = self.audio_bytes_counters.get(client_id, 0) + pcm_data_size
            
            # 每10个包输出一次详细日志，增加日志频率
            if counter == 1 or counter % 100 == 0:
                logger.info(f"[P2P-DATA] 包 #{counter}: 客户端={client_id}, 格式={frame_format}, 采样率={sample_rate}Hz, "
                         f"大小={pcm_data_size} 字节, 累计={self.audio_bytes_counters[client_id]} 字节")
                
            # 每50个包输出详细的WebRTC连接统计信息
            try:
                if counter % 50 == 0 and client_id in webrtc_connections:
                    # 检查WebRTCConnection对象是否有peer_connection属性
                    if hasattr(webrtc_connections[client_id], 'peer_connection') and webrtc_connections[client_id].peer_connection:
                        pc = webrtc_connections[client_id].peer_connection
                        # 异步获取统计信息
                        async def get_stats():
                            stats = await pc.getStats()
                            for stat in stats.values():
                                if stat.type == "inbound-rtp" and stat.kind == "audio":
                                    logger.info(f"[P2P-STATS] 音频接收统计 [客户端: {client_id}] - 已接收包: {stat.packetsReceived}, 丢包: {stat.packetsLost}, 总字节: {stat.bytesReceived}, 解码器实现: {stat.decoderImplementation if hasattr(stat, 'decoderImplementation') else 'unknown'}")
                                elif stat.type == "remote-inbound-rtp" and stat.kind == "audio":
                                    logger.info(f"[P2P-STATS] 远程音频统计 [客户端: {client_id}] - RTT: {stat.roundTripTime if hasattr(stat, 'roundTripTime') else 'N/A'}ms, 丢包率: {stat.fractionLost if hasattr(stat, 'fractionLost') else 'N/A'}")
                        # 创建任务并运行
                        asyncio.create_task(get_stats())
            except Exception as e:
                logger.error(f"[P2P-STATS] 获取WebRTC统计信息失败 [客户端: {client_id}]: {e}")
                logger.error(f"[P2P-STATS] 堆栈跟踪: {traceback.format_exc()}")
            
            # 移除对frame进行深度复制的尝试，因为AudioFrame对象不支持深度复制
            
            # 1. 检查帧格式并准备音频数据
            original_opus_data = None
            converted_opus_data = None
            is_opus_format = hasattr(frame, 'format') and frame.format and frame.format.name.lower() == 'opus'
            is_pcm_format = hasattr(frame, 'format') and frame.format and frame.format.name.lower() in ['s16', 'pcm', 'pcm_s16le']
            
            # 2. 如果是Opus格式，尝试直接提取原始编码数据
            if is_opus_format and hasattr(frame, 'planes') and frame.planes:
                try:
                    original_opus_data = bytes(frame.planes[0])
                    if counter == 1 or counter % 100 == 0:
                        logger.info(f"[P2P-DATA] 成功提取原始Opus编码数据，数据包 #{counter}，大小: {len(original_opus_data)} 字节")
                except Exception as e:
                    logger.warning(f"[P2P-DATA] 提取Opus数据失败: {e}")
                    original_opus_data = None
            
            # 3. 如果是PCM格式(s16)，需要转换为Opus
            pcm_data = None
            if is_pcm_format or original_opus_data is None:
                # 获取PCM数据
                if hasattr(frame, 'to_ndarray'):
                    try:
                        # 先获取数组，再检查其有效性
                        audio_array = frame.to_ndarray()
                        if audio_array is not None and audio_array.size > 0:
                            pcm_data = audio_array.tobytes()
                                                        
                            # 将PCM数据转换为Opus格式
                            sample_rate = frame.sample_rate if hasattr(frame, 'sample_rate') else 16000
                            channels = 1  # 假定单声道
                            frame_size = len(audio_array) // channels
                            
                            converted_opus_data = encode_pcm_to_opus(pcm_data, sample_rate, channels, frame_size)
                            if converted_opus_data:
                                if counter == 1 or counter % 100 == 0:
                                    logger.info(f"[P2P-DATA] PCM数据成功转换为Opus格式，数据包 #{counter}，原始PCM大小: {len(pcm_data)}字节，Opus大小: {len(converted_opus_data)}字节")
                            else:
                                logger.warning(f"[P2P-DATA] PCM转换为Opus失败，数据包 #{counter}")
                        else:
                            logger.warning(f"[P2P-DATA] 音频数组非有效，无法提取PCM数据")
                    except Exception as e:
                        logger.error(f"[P2P-DATA] 处理PCM数据失败: {e}")
                        logger.error(f"[P2P-DATA] 错误详情: {traceback.format_exc()}")
                else:
                    logger.warning(f"[P2P-DATA] 音频帧不支持to_ndarray方法，数据包 #{counter}")
            
            # 4. 更新统计信息
            # 优先使用原始Opus > 转换的Opus > PCM数据
            audio_data_size = 0
            if original_opus_data is not None:
                audio_data_size = len(original_opus_data)
                if counter % 50 == 0:
                    logger.info(f"[P2P-DATA] 使用原始Opus数据，大小: {audio_data_size} 字节")
            elif converted_opus_data is not None:
                audio_data_size = len(converted_opus_data)
                if counter % 50 == 0:
                    logger.info(f"[P2P-DATA] 使用转换后Opus数据，大小: {audio_data_size} 字节")
            elif pcm_data is not None:
                audio_data_size = len(pcm_data)
                if counter % 50 == 0:
                    logger.info(f"[P2P-DATA] 使用PCM数据，大小: {audio_data_size} 字节")
                
            if audio_data_size > 0:
                self.audio_bytes_counters[client_id] += audio_data_size
        
            # 3. 获取或创建WebRTC连接对象
            if client_id in webrtc_connections:
                conn = webrtc_connections[client_id]
                if counter == 1:
                    logger.info(f"[P2P-DATA] 使用已有WebRTC连接对象，客户端ID: {client_id}")
            else:
                # 如果还没有创建WebRTC连接对象，创建一个新的
                from ..modules.webrtc_connection import WebRTCConnection
                conn = WebRTCConnection(client_id)
                webrtc_connections[client_id] = conn
                logger.info(f"[P2P-DATA] 创建新的WebRTC连接对象，客户端ID: {client_id}")
        
            # 5. 将Opus编码音频数据添加到ASR缓冲区，并保留格式信息
            # 优先使用原始Opus > 转换的Opus > PCM数据
            audio_data_for_asr = None
            data_format = None
            is_encoded = False
            
            if original_opus_data is not None:
                audio_data_for_asr = original_opus_data
                data_format = 'opus'
                is_encoded = True
            elif converted_opus_data is not None:
                audio_data_for_asr = converted_opus_data
                data_format = 'opus-converted'
                is_encoded = True
            elif pcm_data is not None:
                audio_data_for_asr = pcm_data
                data_format = 'pcm'
                is_encoded = False
                
            if audio_data_for_asr is not None:
                # 存储音频数据的格式信息，以便后续处理时使用
                audio_data_with_format = {
                    'data': audio_data_for_asr,
                    'format': data_format,
                    'is_encoded': is_encoded,
                    'original_format': frame_format,  # 原始帧格式
                    'sample_rate': sample_rate,
                    'timestamp': time.time()
                }
                conn.asr_audio.append(audio_data_with_format)
                if counter == 1 or counter % 50 == 0:
                    logger.info(f"[P2P-DATA] {data_format}格式音频数据已添加到ASR缓冲区，客户端: {client_id}, 包 #{counter}, 当前已收集 {len(conn.asr_audio)} 段音频")
            else:
                logger.warning(f"[P2P-DATA] 无可用的音频数据传递给ASR, 数据包 #{counter}")
                
                # 尝试使用备用方法提取PCM数据
                try:
                    if hasattr(frame, 'planes') and frame.planes and len(frame.planes) > 0:
                        # 尝试从音频帧的planes直接提取数据
                        raw_data = bytes(frame.planes[0])
                        if raw_data:
                            pcm_data = raw_data
                            logger.info(f"[P2P-DATA] 使用备用方法成功提取PCM数据，大小: {len(pcm_data)} 字节")
                            
                            # 尝试转换为Opus
                            sample_rate = frame.sample_rate if hasattr(frame, 'sample_rate') else 16000
                            converted_opus_data = encode_pcm_to_opus(pcm_data, sample_rate, 1, 960)  # 默认使用960的帧大小
                            if converted_opus_data:
                                logger.info(f"[P2P-DATA] 备用方法PCM数据成功转换为Opus格式，数据包 #{counter}")
                                
                                # 更新音频数据以便ASR处理
                                audio_data_for_asr = converted_opus_data
                                data_format = 'opus-converted-fallback'
                                is_encoded = True
                                
                                # 再次添加到ASR缓冲区
                                audio_data_with_format = {
                                    'data': audio_data_for_asr,
                                    'format': data_format,
                                    'is_encoded': is_encoded,
                                    'original_format': frame_format,
                                    'sample_rate': sample_rate,
                                    'timestamp': time.time()
                                }
                                conn.asr_audio.append(audio_data_with_format)
                                logger.info(f"[P2P-DATA] 使用备用方法成功添加音频数据到ASR缓冲区，数据包 #{counter}")
                except Exception as e:
                    logger.error(f"[P2P-DATA] 备用PCM提取方法失败: {e}")
            
            # 4. 音频包计数器 - 使用已经递增过的counter值
            packet_counter = counter
            
            # 5. 删除基于音频段数量自动触发ASR的逻辑
            # 现在我们让VAD解决何时触发ASR处理
            
            # 6. 处理Push-to-Talk停止请求 - 只转发给VAD处理模块
            try:
                global_stop_requested = getattr(builtins, 'PUSH_TO_TALK_STOP_REQUESTED', False)
                client_id_for_stop = getattr(builtins, 'CLIENT_ID_FOR_STOP', None)
                
                # 如果全局停止请求存在并且客户端ID匹配，通知VAD处理
                if global_stop_requested and (client_id_for_stop is None or client_id_for_stop == client_id):
                    if not hasattr(conn, 'vad') or conn.vad is None:
                        # 初始化VAD对象
                        from webrtc.modules.vad_helper import VADHelper
                        conn.vad = VADHelper()
                        logger.info(f"[VAD-INIT] 为连接 {client_id} 初始化VAD助手")
                    
                    # 调用VAD帮助器标记语音结束
                    logger.warning(f"[PTT-STOP] 检测到全局Push-to-Talk停止请求。正在标记语音结束")
                    conn.vad.mark_speech_end(conn)  # 调用VAD帮助器标记语音结束
                    setattr(builtins, 'PUSH_TO_TALK_STOP_REQUESTED', False)  # 重置全局标志
            except Exception as e:
                logger.warning(f"[PTT-ERROR] 处理Push-to-Talk停止请求时出错: {e}")
            
            # 7. 检测是否需要触发ASR处理
            # 简化语音结束的判断逻辑
            speech_ended = conn.client_voice_stop and len(conn.asr_audio) > 0
            
            # 8. 当检测到语音结束时，调用ASR处理
            if speech_ended:
                # 使用集中处理方法进行ASR识别
                await self._process_audio_for_asr(conn, client_id)
            else:
                # 常规音频处理流程
                # 简化的VAD处理逻辑，专注于将音频数据传递给VADHelper
                try:
                    # 准备要传递给VAD的音频数据
                    audio_data_for_vad = None
                    vad_format = "unknown"
                    
                    # 优先选择最适合的音频格式进行VAD处理
                    if original_opus_data is not None:
                        audio_data_for_vad = original_opus_data
                        vad_format = "opus-original"
                    elif converted_opus_data is not None:
                        audio_data_for_vad = converted_opus_data
                        vad_format = "opus-converted"
                    elif pcm_data is not None:
                        audio_data_for_vad = pcm_data
                        vad_format = "pcm"
                    
                    if audio_data_for_vad is not None:
                        # 确保VAD对象已初始化
                        if not hasattr(conn, 'vad') or conn.vad is None:
                            # 初始化VAD对象
                            from webrtc.modules.vad_helper import VADHelper
                            conn.vad = VADHelper()
                            logger.info(f"[VAD-INIT] 为连接 {client_id} 初始化VAD助手")
                        
                        # 统一调用VAD处理方法
                        logger.debug(f"[VAD-PROCESS] 处理音频数据: 格式={vad_format}, 大小={len(audio_data_for_vad)} 字节")
                        
                        # 调用VADHelper.process方法处理音频数据
                        # 这是统一的入口点，确保所有音频都经过VAD处理
                        try:
                            is_speech, prob = conn.vad.process(audio_data_for_vad, conn)
                        except Exception as vad_error:
                            logger.error(f"[VAD-ERROR] 调用VAD处理失败: {vad_error}")
                    else:
                        logger.warning(f"[VAD-SKIP] 无可用的音频数据用于VAD处理，数据包 #{packet_counter}")
                except Exception as e:
                    logger.error(f"[VAD-ERROR] 音频数据处理失败: {str(e)}")
                    logger.error(f"[VAD-ERROR] 错误详情: {traceback.format_exc()}")
                    
            
            # 9. 更新统计信息
            client_info = self.client_stats.get(client_id, {'frames_processed': 0, 'bytes_processed': 0})
            client_info['frames_processed'] = client_info.get('frames_processed', 0) + 1
            client_info['bytes_processed'] = client_info.get('bytes_processed', 0) + len(audio_array)
            self.client_stats[client_id] = client_info
            
            # 10. 定期输出统计信息
            if client_info['frames_processed'] % 100 == 0:
                logger.info(f"WebRTC已处理 {client_info['frames_processed']} 帧音频 [客户端: {client_id}]")
            
            return None
            
        except Exception as e:
            logger.error(f"[SERVER-AUDIO-ERROR] 处理音频帧时出错: {str(e)}")
            logger.error(f"[SERVER-AUDIO-ERROR] 错误详情: {e.__class__.__name__}: {str(e)}")
            logger.error(f"[SERVER-AUDIO-ERROR] 堆栈跟踪: {traceback.format_exc()}")
            return None
