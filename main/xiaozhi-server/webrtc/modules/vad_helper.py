#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
VAD辅助模块
负责语音活动检测(Voice Activity Detection)功能
"""

import logging
import traceback
import time
import numpy as np

logger = logging.getLogger(__name__)

class VADHelper:
    """语音活动检测(VAD)辅助类"""
    
    def __init__(self):
        """初始化VAD辅助类"""
        self.logger = logger
        # 初始化VAD提供者（延迟加载）
        self.vad = None
        
    def mark_speech_end(self, conn):
        """
        标记语音结束，处理缓冲音频，并触发ASR处理
        
        Args:
            conn: WebRTC连接对象
            
        Returns:
            bool: 是否处理了音频数据并触发ASR
        """
        if conn is None:
            logger.warning("[VAD-MARK-END] 无法标记语音结束：连接对象为None")
            return False
    
        # 从音频缓冲区获取数据
        has_audio_data = False
        audio_data = None
        
        # 1. 先处理VAD缓冲区中的音频数据
        if hasattr(conn, 'audio_buffer') and conn.audio_buffer.get('data') and len(conn.audio_buffer['data']) > 0:
            logger.info(f"[VAD-MARK-END] 处理VAD缓冲区音频: {conn.audio_buffer['frame_count']} 帧")
            try:
                # 合并音频数据
                combined_data = b''.join(conn.audio_buffer['data'])
                combined_size = len(combined_data)
                
                # 清空缓冲区
                conn.audio_buffer['data'] = []
                conn.audio_buffer['total_size'] = 0
                conn.audio_buffer['frame_count'] = 0
                conn.audio_buffer['last_append_time'] = time.time()
                
                # 调用VAD处理合并后的音频
                self._ensure_vad_loaded()
                is_speech, prob = self.vad.is_speech(combined_data)
                
                # 记录处理结果
                logger.info(f"[VAD-MARK-END] VAD处理结果: is_speech={is_speech}, 概率={prob}, 数据大小={combined_size}")
                
                # 将处理后的音频数据转发给ASR
                if is_speech or prob > 0.3:  # 即使概率低也尝试转发，因为这是用户主动结束的情况
                    audio_data = combined_data
                    has_audio_data = True
            except Exception as e:
                logger.error(f"[VAD-MARK-END-ERROR] 处理缓冲区音频失败: {e}")
        
        # 2. 将处理后的音频数据添加到ASR缓冲区
        if has_audio_data and audio_data and hasattr(conn, 'asr_audio'):
            audio_data_with_format = {
                'data': audio_data,
                'format': 'opus-processed',  # 标记为处理过的数据
                'is_encoded': True,
                'timestamp': time.time()
            }
            conn.asr_audio.append(audio_data_with_format)
            logger.info(f"[VAD-MARK-END] 添加处理后的数据到ASR缓冲区，当前音频段数量: {len(conn.asr_audio)}")
        
        # 3. 标记语音状态
        conn.client_have_voice = True  # 确保已标记有语音
        conn.client_voice_stop = True  # 标记语音结束
        
        if hasattr(conn, 'client_voice_stop_requested'):
            conn.client_voice_stop_requested = True
            
        logger.warning(f"[VAD-MARK-END] 标记语音结束，处理状态: has_audio={has_audio_data}, 当前音频段数量: {len(getattr(conn, 'asr_audio', []))}")
        
        # 4. 重置计数器
        conn.vad_silence_count = 0
        conn.vad_speech_count = 0
        
        return True
        
    def _ensure_vad_loaded(self):
        """确保VAD模型已加载"""
        if self.vad is None:
            try:
                from core.providers.vad import get_vad_provider
                self.vad = get_vad_provider()
                logger.info(f"[VAD-DEBUG] VAD提供者加载成功: {self.vad.__class__.__name__}")
                
                # 记录VAD配置信息
                try:
                    from config.config_loader import load_config
                    config = load_config()
                    vad_config = config.get('VAD', {})
                    selected_vad = config.get('selected_module', {}).get('VAD')
                    logger.info(f"[VAD-DEBUG] VAD配置: 已选择{selected_vad}, 可用配置: {list(vad_config.keys())}")
                except Exception as config_err:
                    logger.warning(f"[VAD-DEBUG] 无法加载VAD配置: {config_err}")
            except Exception as e:
                logger.error(f"[VAD-DEBUG] VAD提供者加载失败: {e}")
                logger.error(f"[VAD-DEBUG] 错误详情: {traceback.format_exc()}")
    
    def _is_vad(self, conn, audio):
        """
        使用VAD检测音频中是否有语音活动
        
        Args:
            conn: WebRTC连接对象
            audio: 音频数据
            
        Returns:
            bool: 是否检测到语音活动
        """
        try:
            if audio is None:
                logger.warning("[VAD-INFO] 音频数据为None，无法处理")
                return False
                
            # 确保VAD模型已加载
            self._ensure_vad_loaded()
            
            if len(audio) == 0:
                return False
                
            # 尝试识别音频格式
            try:
                if audio.startswith(b'OggS') or audio.startswith(b'OpusHead'):
                    pass
            except Exception as check_err:
                logger.warning(f"[VAD-INFO] 检查音频格式失败: {check_err}")
                
            # 尝试从连接对象获取音频格式信息
            try:
                if hasattr(conn, 'audio_format'):
                    logger.debug(f"[VAD-INFO] 连接音频格式: {conn.audio_format}")
                if hasattr(conn, 'sample_rate'):
                    logger.debug(f"[VAD-INFO] 连接音频采样率: {conn.sample_rate} Hz")
            except Exception as conn_err:
                logger.warning(f"[VAD-INFO] 无法获取连接音频配置: {conn_err}")
            
            # 始终记录VAD调用日志，不再使用计数器限制
            logger.info(f"[VAD-CALL] 开始调用VAD识别，音频数据长度: {len(audio)} 字节")
                
            is_speech, prob = self.process(audio, conn)
            
            # 始终记录VAD结果日志，不再使用计数器限制
            logger.info(f"[VAD-RESULT] VAD检测结果: 有语音活动={is_speech}, 概率: {prob}")
            
            # 更新连接状态
            if is_speech:
                conn.client_have_voice = True
                conn.vad_speech_count = conn.vad_speech_count + 1 if hasattr(conn, 'vad_speech_count') else 1
            else:
                conn.vad_silence_count = conn.vad_silence_count + 1 if hasattr(conn, 'vad_silence_count') else 1
                
                # 如果连续静音超过一定阈值，可能声音结束
                if getattr(conn, 'vad_silence_count', 0) > 5 and getattr(conn, 'client_have_voice', False):
                    conn.client_voice_stop = True
                    logger.info("[VAD-DEBUG] 检测到语音结束，已设置client_voice_stop=True")
            
            return is_speech
        except Exception as e:
            logger.error(f"[VAD-ERROR] VAD判断出错: {str(e)}")
            logger.error(f"[VAD-ERROR] 错误详情: {e.__class__.__name__}: {str(e)}")
            logger.error(f"[VAD-ERROR] 堆栈跟踪: {traceback.format_exc()}")
            return False
    
    def process(self, audio_data, conn=None):
        """
        处理音频数据，检测是否有语音活动
        使用统一的音频缓冲区队列系统来提高VAD准确性
        并将检测到的语音数据直接传递给ASR缓冲区
        
        Args:
            audio_data: 音频数据（可能是PCM或Opus格式）
            conn: WebRTC连接对象（可选）
        
        Returns:
            tuple: (is_speech, probability)
        """
        try:
            self._ensure_vad_loaded()
            
            # 如果没有连接对象，直接处理并返回结果
            if conn is None:
                is_speech, prob = self.vad.is_speech(audio_data)
                return is_speech, prob
                
            # 如果连接对象已标记为不接收音频，跳过处理
            if hasattr(conn, 'asr_server_receive') and not conn.asr_server_receive:
                logger.debug("[VAD-PROCESS] 服务器暂停接收音频，跳过VAD处理")
                return False, 0.0
            
            # ===== 预处理音频数据 =====
            data_size = len(audio_data)
            
            # ===== 缓冲区处理逻辑 =====
            # 初始化音频缓冲区（如果不存在）
            if not hasattr(conn, 'audio_buffer'):
                conn.audio_buffer = {
                    'data': [],                   # 音频数据缓冲区
                    'last_append_time': time.time(),  # 上次添加数据的时间
                    'total_size': 0,               # 缓冲区当前总大小
                    'frame_count': 0                # 帧计数器
                }
            
            # 添加数据到缓冲区
            conn.audio_buffer['data'].append(audio_data)
            conn.audio_buffer['last_append_time'] = time.time()
            conn.audio_buffer['total_size'] += data_size
            conn.audio_buffer['frame_count'] += 1
            
            # 获取当前缓冲区状态
            total_size = conn.audio_buffer['total_size']
            frame_count = conn.audio_buffer['frame_count']
            
            # 记录缓冲区状态（控制日志量）
            if frame_count % 10 == 0 or frame_count <= 2:
                logger.debug(f"[VAD-BUFFER-STATUS] 当前缓冲状态: {frame_count}帧/{total_size}字节, 阈值: 500帧/64000字节")
            
            # 判断是否应该处理缓冲区数据
            process_buffer = False
            process_reason = ""
            
            # 情况1: 缓冲区达到处理阈值 (64000字节或至少500帧)
            if total_size >= 64000 or frame_count >= 500:  
                process_buffer = True
                process_reason = "达到处理阈值"
            # 情况2: 缓冲区超时（确保音频不会永远积累不处理）
            elif time.time() - conn.audio_buffer['last_append_time'] > 3.0 and frame_count > 0:  
                process_buffer = True
                process_reason = "缓冲区超时"
            
            # 如果需要处理缓冲区
            if process_buffer:
                logger.info(f"[VAD-BUFFER-PROCESS] 处理原因: {process_reason}, 缓冲区状态: {frame_count}帧/{total_size}字节")
                try:
                    # 合并音频数据
                    combined_data = b''.join(conn.audio_buffer['data'])
                    combined_size = len(combined_data)
                    
                    # 清空缓冲区
                    conn.audio_buffer['data'] = []
                    conn.audio_buffer['total_size'] = 0
                    conn.audio_buffer['frame_count'] = 0
                    conn.audio_buffer['last_append_time'] = time.time()
                    
                    # 调用VAD处理合并后的音频
                    logger.info(f"[VAD-CALL] 处理合并音频，原因: {process_reason}，大小: {combined_size} 字节")
                    self._ensure_vad_loaded()
                    is_speech, prob = self.vad.is_speech(combined_data)
                    
                    # 记录处理结果
                    logger.info(f"[VAD-RESULT] 合并处理结果: is_speech={is_speech}, 概率={prob}")
                    
                    # 将检测到的语音数据传递给ASR缓冲区
                    if is_speech and prob > 0.45 and hasattr(conn, 'asr_audio'):
                        try:
                            # 将处理后的数据添加到ASR缓冲区
                            audio_data_with_format = {
                                'data': combined_data,
                                'format': 'opus-vad-processed',  # 标记为VAD处理过的数据
                                'is_encoded': True,
                                'timestamp': time.time(),
                                'prob': prob  # 保存VAD置信度
                            }
                            conn.asr_audio.append(audio_data_with_format)
                            logger.info(f"[VAD-TO-ASR] 检测到语音，添加到ASR缓冲区，当前音频段数: {len(conn.asr_audio)}")
                            
                            # 标记已检测到语音
                            conn.client_have_voice = True
                            
                            # 更新VAD语音计数器
                            if not hasattr(conn, 'vad_speech_count'):
                                conn.vad_speech_count = 0
                            conn.vad_speech_count += 1
                            
                            # 重置静音计数器
                            if hasattr(conn, 'vad_silence_count'):
                                conn.vad_silence_count = 0
                        except Exception as e:
                            logger.error(f"[VAD-TO-ASR-ERROR] 添加数据到ASR缓冲区失败: {e}")
                    elif not is_speech and hasattr(conn, 'client_have_voice') and conn.client_have_voice:
                        # 如果之前检测到语音，但现在是静音，更新静音计数器
                        if not hasattr(conn, 'vad_silence_count'):
                            conn.vad_silence_count = 0
                        conn.vad_silence_count += 1
                        
                        # 如果连续检测到一定数量的静音，可能表示语音结束
                        if conn.vad_silence_count >= 3 and hasattr(conn, 'vad_speech_count') and conn.vad_speech_count > 0:
                            logger.info(f"[VAD-END-SPEECH] 检测到可能的语音结束，静音计数: {conn.vad_silence_count}, 语音计数: {conn.vad_speech_count}")
                            if len(getattr(conn, 'asr_audio', [])) > 0:
                                # 如果有一定量的音频数据，标记语音结束
                                conn.client_voice_stop = True
                                logger.warning(f"[VAD-AUTO-END] 自动检测到语音结束，已标记 client_voice_stop=True, 音频段数: {len(conn.asr_audio)}")
                    
                    # 对于短音频的超时处理，可以稍微提高概率
                    if process_reason == "缓冲区超时" and combined_size < 3200:
                        adjusted_prob = max(0.4, prob)
                        logger.debug(f"[VAD-ADJUST] 短音频调整: 调整前={prob}, 调整后={adjusted_prob}")
                        return is_speech, adjusted_prob
                    
                    return is_speech, prob
                    
                except Exception as e:
                    logger.error(f"[VAD-ERROR] 缓冲区处理失败: {e}")
                    logger.error(f"[VAD-ERROR] 错误详情: {traceback.format_exc()}")
                    # 出错时清空缓冲区
                    conn.audio_buffer['data'] = []
                    conn.audio_buffer['total_size'] = 0
                    conn.audio_buffer['frame_count'] = 0
                    # 错误情况下返回默认值
                    return False, 0.0
            else:
                # 数据已缓冲但还不需要处理，返回暂无语音标志
                return False, 0.0
                
        except Exception as e:
            logger.error(f"[VAD-ERROR] VAD处理错误: {str(e)}")
            logger.error(f"[VAD-ERROR] 错误详情: {traceback.format_exc()}")
            return False, 0.0
