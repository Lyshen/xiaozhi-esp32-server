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

from config.logger import setup_logging

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
            # 记录音频帧的详细信息
            logger.info(f"[AUDIO-DEBUG] 音频帧信息 - 格式: {frame.format.name}, 采样率: {frame.sample_rate}, 通道: {frame.layout.name}, 样本数: {len(frame.to_ndarray())}")
            
            # 检查是否是opus格式
            if hasattr(frame.format, 'name') and frame.format.name.lower() == 'opus':
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
            
            # 检查音频数据是否为空
            audio_array = frame.to_ndarray()
            if audio_array.size == 0:
                logger.warning(f"[AUDIO-DEBUG] 音频数据为空，无法转换")
                return b''
                
            pcm_data = audio_array.flatten().tobytes()
            logger.info(f"[AUDIO-DEBUG] PCM转换完成，输出长度: {len(pcm_data)} 字节，前10字节: {pcm_data[:10]}")
            # 保存原始格式信息，便于后续处理
            return pcm_data
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
            
            # 1. 检查帧格式，优先保留原始编码数据而不解码
            original_opus_data = None
            is_opus_format = hasattr(frame, 'format') and frame.format and frame.format.name.lower() == 'opus'
            
            # 无论格式如何，都尝试直接保留原始编码数据
            if hasattr(frame, 'planes') and frame.planes:
                try:
                    # 保留原始编码数据，不进行解码
                    original_opus_data = bytes(frame.planes[0])
                    if counter == 1 or counter % 100 == 0:
                        logger.info(f"[P2P-DATA] 成功提取原始编码数据，数据包 #{counter}，格式: {frame_format}，大小: {len(original_opus_data)} 字节")
                        logger.info(f"[P2P-DATA] 直接传递原始编码数据到后续处理流程，不进行解码")
                except Exception as e:
                    logger.warning(f"[P2P-DATA] 提取原始编码数据失败: {e}，将回退到PCM转换")
                    original_opus_data = None
        
            # 2. 只在无法获取原始编码数据时才进行PCM转换（作为后备方案）
            pcm_data = None
            if original_opus_data is None:
                logger.warning(f"[P2P-DATA] 无法获取原始编码数据，尝试PCM转换作为后备方案")
                pcm_data = await self.convert_audio_to_pcm(frame)
                if counter == 1 or counter % 100 == 0:
                    logger.info(f"[P2P-DATA] PCM转换完成（后备方案），数据包 #{counter}，大小: {len(pcm_data)} 字节")
                self.audio_bytes_counters[client_id] += len(pcm_data)
            else:
                self.audio_bytes_counters[client_id] += len(original_opus_data)
        
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
        
            # 4. 将原始编码音频数据添加到ASR缓冲区，并保留格式信息
            audio_data_for_asr = original_opus_data if original_opus_data is not None else pcm_data
            if audio_data_for_asr is not None:
                # 存储音频数据的原始格式信息，以便后续处理时使用
                audio_data_with_format = {
                    'data': audio_data_for_asr,
                    'format': frame_format,
                    'is_encoded': original_opus_data is not None,
                    'timestamp': time.time()
                }
                conn.asr_audio.append(audio_data_with_format)
                if counter % 100 == 0:
                    format_type = '原始编码' if original_opus_data is not None else 'PCM'
                    logger.info(f"[P2P-DATA] {format_type}音频数据已添加到ASR缓冲区，客户端: {client_id}, 包 #{counter}, 当前已收集 {len(conn.asr_audio)} 段音频")
            
            # 4. 音频包计数器
            packet_counter = self.audio_packet_counters[client_id]
            
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
                    # 提取音频数据，保留原始格式
                    raw_audio_data = [item['data'] if isinstance(item, dict) else item for item in conn.asr_audio]
                    
                    # 检查第一个元素是否包含格式信息
                    has_format_info = len(conn.asr_audio) > 0 and isinstance(conn.asr_audio[0], dict) and 'format' in conn.asr_audio[0]
                    if has_format_info and conn.asr_audio[0]['format'].lower() == 'opus':
                        logger.info(f"[SERVER-AUDIO] 正在处理原始Opus编码的音频数据 ({len(raw_audio_data)} 段)")
                    else:
                        logger.info(f"[SERVER-AUDIO] 处理音频数据 ({len(raw_audio_data)} 段)，格式: {'原始格式' if has_format_info else 'PCM/未知'}")
                    
                    text, extra_info = await conn.asr.speech_to_text(raw_audio_data, conn.session_id)
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
                    
                    # 使用正确的音频数据格式调用VAD处理逻辑
                    audio_data_for_vad = original_opus_data if is_opus_format and original_opus_data is not None else pcm_data
                    
                    # 检查音频数据是否为None，避免传递None数据给VAD
                    if audio_data_for_vad is None:
                        logger.warning(f"[P2P-DATA] 无可用音频数据，跳过VAD处理，数据包 #{packet_counter}")
                        result = None
                    else:
                        if packet_counter % 100 == 0:
                            format_type = "Opus" if is_opus_format and original_opus_data is not None else "PCM"
                            logger.info(f"[P2P-DATA] 正常VAD处理，数据包 #{packet_counter}，格式: {format_type}，音频长度: {len(audio_data_for_vad)} 字节")
                        
                        # 传递有效的音频数据给VAD处理函数
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
