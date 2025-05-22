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
    
    def is_vad(self, conn, audio):
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
        
        Args:
            audio_data: 音频数据（可能是PCM或Opus格式）
            conn: WebRTC连接对象（可选）
        
        Returns:
            tuple: (is_speech, probability)
        """
        try:
            self._ensure_vad_loaded()
            
            # ===== 预处理音频数据 =====
            data_size = len(audio_data)
            
            # 对于大尺寸音频数据，直接处理
            if data_size >= 3200 or not conn:
                # 控制日志频率
                if not hasattr(self, 'direct_log_counter'):
                    self.direct_log_counter = 0
                self.direct_log_counter = (self.direct_log_counter + 1) % 10
                
                if self.direct_log_counter == 0:
                    logger.info(f"[VAD-INFO] 直接处理大尺寸音频数据，长度: {data_size} 字节")
                
                # 调用VAD处理
                logger.info(f"[VAD-CALL] 直接处理大尺寸音频数据，长度: {data_size} 字节")
                is_speech, prob = self.vad.is_speech(audio_data)
                
                logger.info(f"[VAD-RESULT] VAD结果: is_speech={is_speech}, 概率={prob}")
                return is_speech, prob
            
            # ===== 统一的音频缓冲区管理 =====
            # 初始化音频缓冲区
            if not hasattr(conn, 'audio_buffer'):
                conn.audio_buffer = {
                    'data': [],              # 音频数据缓冲区
                    'last_append_time': time.time(),  # 上次添加数据的时间
                    'total_size': 0,        # 缓冲区当前总大小
                    'frame_count': 0         # 帧计数器
                }
                
                # 添加数据到缓冲区并更新元数据
                conn.audio_buffer['data'].append(audio_data)
                conn.audio_buffer['last_append_time'] = time.time()
                conn.audio_buffer['total_size'] += len(audio_data)
                conn.audio_buffer['frame_count'] += 1
                
                total_size = conn.audio_buffer['total_size']
                frame_count = conn.audio_buffer['frame_count']
                
                # 每10个包记录一次缓冲区状态（避免日志过多）
                if frame_count % 10 == 0 or frame_count <= 2:
                    logger.info(f"[VAD-BUFFER] 已累积 {frame_count} 个音频片段，总大小:{total_size}字节")
                
                # 判断是否应该处理缓冲区数据
                process_buffer = False
                process_reason = ""
                
                # 情况1: 缓冲区达到处理阈值 (64000字节或至少500帧)
                # 记录当前缓冲区状态 - 确保所有状态都被记录
                logger.info(f"[VAD-BUFFER-STATUS] 当前缓冲状态: {frame_count}帧/{total_size}字节, 阈值: 500帧/64000字节, 上次添加时间: {time.time() - conn.audio_buffer['last_append_time']:.2f}秒前")
                if total_size >= 64000 or frame_count >= 500:  
                    process_buffer = True
                    process_reason = "达到处理阈值"
                
                # 情况2: 缓冲区超时（确保音频不会永远积累不处理）
                elif time.time() - conn.audio_buffer['last_append_time'] > 3.0 and frame_count > 0:  # 3秒超时
                    process_buffer = True
                    process_reason = "缓冲区超时"
                
                # 如果需要处理缓冲区
                if process_buffer and frame_count > 0:
                    logger.info(f"[VAD-BUFFER-PROCESS] 处理原因: {process_reason}, 缓冲区状态: {frame_count}帧/{total_size}字节")
                    try:
                        # 合并音频数据
                        combined_data = b''.join(conn.audio_buffer['data'])
                        combined_size = len(combined_data)
                        
                        # 记录合并状态
                        logger.info(f"[VAD-PROCESS] {process_reason}，处理缓冲区: {frame_count}个片段，大小{combined_size}字节")
                        
                        # 清空缓冲区
                        conn.audio_buffer['data'] = []
                        conn.audio_buffer['total_size'] = 0
                        conn.audio_buffer['frame_count'] = 0
                        conn.audio_buffer['last_append_time'] = time.time()
                        
                        # 调用VAD处理 - 确保一致的日志格式
                        logger.info(f"[VAD-CALL] 调用VAD处理合并音频，数据长度: {combined_size} 字节")
                        is_speech, prob = self.vad.is_speech(combined_data)
                        
                        # 记录VAD处理完成
                        logger.info(f"[VAD-PROCESS-COMPLETED] 已完成VAD处理，结果: is_speech={is_speech}, 概率={prob}, 原因: {process_reason}")
                        
                        # 根据处理原因调整返回值
                        if process_reason == "缓冲区超时" and combined_size < 3200:
                            # 对于短音频的超时处理，稍微提高概率以确保短音频能被后续处理
                            adjusted_prob = max(0.4, prob)
                            logger.info(f"[VAD-RESULT] VAD结果: is_speech={is_speech}, 调整前概率={prob}, 调整后概率={adjusted_prob}")
                            return is_speech, adjusted_prob
                        else:
                            logger.info(f"[VAD-RESULT] VAD结果: is_speech={is_speech}, 概率={prob}")
                            return is_speech, prob
                    except Exception as e:
                        logger.error(f"[VAD-ERROR] 音频处理失败: {e}")
                        # 出错时清空缓冲区防止持续累积错误数据
                        conn.audio_buffer['data'] = []
                        conn.audio_buffer['total_size'] = 0
                        conn.audio_buffer['frame_count'] = 0
                
                # 如果是新添加的数据（不需要立即处理），返回延迟处理标志
                if not process_buffer:
                    # 提高日志级别，确保缓冲状态始终可见
                    logger.info(f"[VAD-BUFFER] 音频数据已加入缓冲区，待积累足够数据后处理，当前已累积: {frame_count}个片段/{total_size}字节，距离处理阈值还需: {max(0, 500-frame_count)}帧/{max(0, 64000-total_size)}字节")
                    return False, 0.0  # 返回False表示当前未检测到语音，但数据已被累积
            # 缓冲区逻辑结束后，如果没有返回值，返回默认值
            logger.info(f"[VAD-CALL] 单次调用VAD处理音频，长度: {len(audio_data)} 字节")
            # 直接调用VAD
            is_speech, prob = self.vad.is_speech(audio_data)
            logger.info(f"[VAD-RESULT] 单次VAD结果: is_speech={is_speech}, 概率={prob}")
            return is_speech, prob
        except Exception as e:
            logger.error(f"[VAD-ERROR] VAD处理错误: {str(e)}")
            logger.error(f"[VAD-ERROR] 错误详情: {e.__class__.__name__}: {str(e)}")
            logger.error(f"[VAD-ERROR] 堆栈跟踪: {traceback.format_exc()}")
            return False, 0.0
