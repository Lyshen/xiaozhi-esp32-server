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
        # 复制自 _convert_audio_to_pcm 方法
        pcm_data = frame.to_ndarray().flatten().tobytes()
        return pcm_data
        
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
            
            # 添加明确的日志 - 记录开始处理音频
            logger.warning(f"[SERVER-AUDIO] 接收音频包 #{counter} 来自客户端 {client_id}, 时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
            
            # 1. 将音频帧转换为PCM格式 (原VAD链路需要的格式)
            audio_array = await self.convert_audio_to_pcm(frame)
            self.audio_bytes_counters[client_id] += len(audio_array)
            logger.warning(f"[SERVER-AUDIO] 音频转换完成，数据包 #{counter}，大小: {len(audio_array)} 字节，累计: {self.audio_bytes_counters[client_id]} 字节")
            
            # 2. 获取或创建持久化的WebRTC连接对象
            if client_id in webrtc_connections:
                conn = webrtc_connections[client_id]
                logger.warning(f"[SERVER-AUDIO] 使用已有WebRTC连接对象，客户端ID: {client_id}")
            else:
                # 创建新的WebRTC连接对象并保存
                from ..modules.webrtc_connection import WebRTCConnection
                conn = WebRTCConnection(client_id)
                webrtc_connections[client_id] = conn
                logger.warning(f"[SERVER-AUDIO] 创建新的WebRTC连接对象，客户端ID: {client_id}")
            
            # 3. 将音频数据添加到缓冲区 - 直接添加到ASR音频列表
            conn.asr_audio.append(audio_array)
            logger.warning(f"[SERVER-AUDIO] 音频数据已添加到ASR缓冲区，客户端: {client_id}, 包 #{counter}, 当前已收集 {len(conn.asr_audio)} 段音频")
            
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
                    text, extra_info = await conn.asr.speech_to_text(conn.asr_audio, conn.session_id)
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
                            else:
                                # WebSocket不存在，保存结果到连接对象
                                conn.last_asr_result = text
                                logger.warning(f"[SERVER-AUDIO] WebSocket连接不存在，已保存ASR结果: {text}")
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
                    
                    # 调用原有VAD处理逻辑
                    logger.warning(f"[SERVER-AUDIO] 正常VAD处理，数据包 #{packet_counter}，音频长度: {len(audio_array)} 字节")
                    result = await process_audio_internal(conn, audio_array)
                    logger.warning(f"[SERVER-AUDIO] VAD处理链路已完成，数据包 #{packet_counter}，结果: {result}")
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
