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
            if counter == 1 or counter % 10 == 0:
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
            
            # 5. 当收集到足够多的音频段时（至少15段），设置VAD标志并触发ASR处理
            if len(conn.asr_audio) >= 15 and packet_counter % 30 == 0:
                logger.warning(f"[SERVER-AUDIO] 已收集足够的音频段: {len(conn.asr_audio)} > 15 段，准备触发ASR处理")
                # 设置VAD已检测到语音活动
                conn.client_have_voice = True
                # 标记语音片段结束，触发ASR处理
                conn.client_voice_stop = True
                logger.warning(f"[SERVER-AUDIO] 标记语音状态: have_voice=True, voice_stop=True，将触发ASR处理")
            
            # 6. 检查是否有全局Push-to-Talk停止请求标志
            try:
                global_stop_requested = getattr(builtins, 'PUSH_TO_TALK_STOP_REQUESTED', False)
                client_id_for_stop = getattr(builtins, 'CLIENT_ID_FOR_STOP', None)
                
                # 如果全局标志存在，并且客户端ID匹配，则为当前连接设置停止标志
                if global_stop_requested and (client_id_for_stop is None or client_id_for_stop == client_id):
                    conn.client_voice_stop = True
                    if hasattr(conn, 'client_voice_stop_requested'):
                        conn.client_voice_stop_requested = True
                    logger.warning(f"[ASR-TRIGGER-GLOBAL] 检测到全局Push-to-Talk停止请求，已设置 client_voice_stop=True")
                    # 重置全局标志，避免多次触发
                    setattr(builtins, 'PUSH_TO_TALK_STOP_REQUESTED', False)
            except Exception as e:
                logger.warning(f"[ASR-TRIGGER-ERROR] 检查全局标志时出错: {e}")
            
            # 7. 对ASR触发条件进行详细日志记录
            has_stop_requested_attr = hasattr(conn, 'client_voice_stop_requested')
            condition1 = conn.client_voice_stop and len(conn.asr_audio) >= 15
            condition2 = has_stop_requested_attr and conn.client_voice_stop_requested and len(conn.asr_audio) > 0
            
            # 8. 当触发条件满足时，处理音频数据
            if condition1 or condition2:
                logger.warning(f"[SERVER-AUDIO] 开始处理整合的音频段，总共 {len(conn.asr_audio)} 段，准备调用ASR处理")
                
                # 暂停接收新音频
                conn.asr_server_receive = False
                
                # 直接调用ASR接口处理累积的音频数据
                try:
                    # 提取音频数据，确保所有数据都是Opus格式
                    opus_audio_data = []
                    opus_converted_count = 0
                    opus_original_count = 0
                    pcm_count = 0
                    
                    for item in conn.asr_audio:
                        if isinstance(item, dict) and 'data' in item:
                            data_format = item.get('format', 'unknown')
                            if data_format == 'opus':
                                opus_audio_data.append(item['data'])
                                opus_original_count += 1
                            elif data_format == 'opus-converted':
                                opus_audio_data.append(item['data'])
                                opus_converted_count += 1
                            elif data_format == 'pcm':
                                # PCM数据应该在前面已经转换成Opus了，但为了完整性再次检查
                                pcm_count += 1
                                continue  # 跳过PCM数据，只使用Opus格式
                            else:
                                # 未知格式，作为原始数据使用
                                opus_audio_data.append(item['data'])
                        elif item is not None:
                            # 兼容旧版存储格式，直接存储的数据
                            opus_audio_data.append(item)
                            
                    logger.info(f"[SERVER-AUDIO] 准备处理ASR: 原始Opus: {opus_original_count}段, 转换Opus: {opus_converted_count}段, 原PCM: {pcm_count}段")
                    logger.info(f"[SERVER-AUDIO] 总共有效Opus数据: {len(opus_audio_data)}段")
                    
                    text, extra_info = await conn.asr.speech_to_text(opus_audio_data, conn.session_id)
                    logger.warning(f"[SERVER-AUDIO] ASR识别结果: '{text}'")
                    
                    # 处理识别文本
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
                            vad = builtins_conn.vad
                            print("[VAD-DEBUG] 开始调用VAD识别")
                            
                            # 直接使用最近收集的原始编码数据进行VAD检测
                            try:
                                if len(conn.asr_audio) > 0:
                                    # 获取最近一段音频数据
                                    last_audio = conn.asr_audio[-1]
                                    
                                    if isinstance(last_audio, dict) and 'data' in last_audio:
                                        # 使用保存的格式化音频数据
                                        audio_for_vad = last_audio['data']
                                        is_encoded = last_audio.get('is_encoded', False)
                                        format_type = last_audio.get('format', 'unknown')
                                        
                                        logger.info(f"[VAD-DEBUG] 使用{'原始编码' if is_encoded else 'PCM'}数据进行VAD检测，格式:{format_type}")
                                        vad_result = await vad.is_vad(audio_for_vad, builtins_conn)
                                    else:
                                        # 兼容旧格式，直接使用数据
                                        logger.info(f"[VAD-DEBUG] 使用未格式化的音频数据进行VAD检测")
                                        vad_result = await vad.is_vad(last_audio, builtins_conn)
                                else:
                                    # 如果没有收集到音频数据，尝试使用当前帧
                                    if original_opus_data is not None:
                                        logger.info(f"[VAD-DEBUG] 没有收集到音频数据，使用当前帧的原始编码数据")
                                        vad_result = await vad.is_vad(original_opus_data, builtins_conn)
                                    elif audio_array is not None:
                                        logger.info(f"[VAD-DEBUG] 没有收集到音频数据，使用当前帧的PCM数据")
                                        vad_result = await vad.is_vad(audio_array, builtins_conn)
                                    else:
                                        logger.warning(f"[VAD-DEBUG] 没有可用的音频数据进行VAD检测")
                                        vad_result = None
                            except Exception as vad_error:
                                logger.error(f"[VAD-ERROR] VAD处理失败: {vad_error}")
                                vad_result = None
                                
                            if counter % 100 == 0 or vad_result is not None:
                                logger.info(f"[P2P-DATA] VAD处理链路已完成，数据包 #{counter}，结果: {vad_result}")
                        except Exception as e:
                            logger.error(f"[SERVER-AUDIO-ERROR] 处理ASR结果时发生错误: {e}")
                            logger.error(f"[SERVER-AUDIO-ERROR] 堆栈跟踪: {traceback.format_exc()}")
                except Exception as e:
                    logger.error(f"[SERVER-AUDIO-ERROR] ASR处理失败: {e}")
                
                # 清空音频缓冲区并重置状态
                conn.asr_audio.clear()
                conn.reset_vad_states()
                conn.asr_server_receive = True
                logger.warning("[SERVER-AUDIO] ASR处理完成，已重置状态，恢复接收音频")
            else:
                # 常规音频处理流程
                try:
                    # 尝试导入VAD处理函数
                    try:
                        from main.xiaozhi_server.core.handle.receiveAudioHandle import process_audio_internal
                    except ImportError:
                        from core.handle.receiveAudioHandle import process_audio_internal
                    
                    # 使用正确的Opus编码音频数据调用VAD处理逻辑
                    audio_data_for_vad = None
                    vad_format = "unknown"
                    
                    # 记录VAD处理路径 - 确保我们可以跟踪音频数据的流向
                    logger.info(f"[VAD-PATH] 准备通过音频帧处理器调用VAD处理，数据包 #{packet_counter}")
                    
                    # 优先使用原始Opus > 转换的Opus > PCM数据
                    if original_opus_data is not None:
                        audio_data_for_vad = original_opus_data
                        vad_format = "Opus-original"
                    elif converted_opus_data is not None:
                        audio_data_for_vad = converted_opus_data
                        vad_format = "Opus-converted"
                    elif pcm_data is not None:
                        audio_data_for_vad = pcm_data
                        vad_format = "PCM"
                    
                    # 检查音频数据是否可用，避免传递None数据给VAD
                    if audio_data_for_vad is None:
                        logger.warning(f"[P2P-DATA] 无可用音频数据，跳过VAD处理，数据包 #{packet_counter}")
                        result = None
                    else:
                        if packet_counter % 100 == 0:
                            logger.info(f"[P2P-DATA] 正常VAD处理，数据包 #{packet_counter}，格式: {vad_format}，音频长度: {len(audio_data_for_vad)} 字节")
                        
                        # 确保VAD对象已初始化
                        if not hasattr(conn, 'vad') or conn.vad is None:
                            # 初始化VAD对象
                            from webrtc.modules.vad_helper import VADHelper
                            conn.vad = VADHelper()
                            logger.info(f"[VAD-INIT] 为连接 {client_id} 初始化VAD助手")
                            
                        # 增加清晰的VAD调用链日志
                        logger.info(f"[VAD-CHAIN] 数据格式: {vad_format}, 大小: {len(audio_data_for_vad)} 字节, 即将调用VAD处理")
                            
                        # 直接调用VAD助手而不是process_audio_internal
                        # 这确保了所有音频都通过VAD助手处理
                        try:
                            # VADHelper.process不是异步方法，直接同步调用
                            is_speech, prob = conn.vad.process(audio_data_for_vad, conn)
                            logger.info(f"[VAD-DIRECT-RESULT] 直接VAD处理结果: 有语音={is_speech}, 概率={prob}")
                            
                            # 更新连接状态
                            if is_speech:
                                conn.client_have_voice = True
                                conn.vad_speech_count = conn.vad_speech_count + 1 if hasattr(conn, 'vad_speech_count') else 1
                            else:
                                conn.vad_silence_count = conn.vad_silence_count + 1 if hasattr(conn, 'vad_silence_count') else 1
                                
                                # 如果连续静音超过一定阈值，可能声音结束
                                if getattr(conn, 'vad_silence_count', 0) > 5 and getattr(conn, 'client_have_voice', False):
                                    conn.client_voice_stop = True
                                    logger.info(f"[VAD-DIRECT-STOP] 检测到语音可能已结束，设置client_voice_stop=True")
                            
                            result = is_speech
                        except Exception as vad_error:
                            logger.error(f"[VAD-DIRECT-ERROR] 直接调用VAD处理失败: {vad_error}")
                            logger.error(f"[VAD-DIRECT-ERROR] 回退到process_audio_internal处理")
                            
                            # 回退到原有流程
                            result = await process_audio_internal(conn, audio_data_for_vad)
                    if packet_counter % 100 == 0 or result is not None:
                        logger.info(f"[P2P-DATA] VAD处理链路已完成，数据包 #{packet_counter}，结果: {result}")
                except ImportError as e:
                    logger.error(f"[SERVER-AUDIO] 无法导入VAD处理链路: {str(e)}")
            
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
