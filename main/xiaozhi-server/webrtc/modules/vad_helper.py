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
        判断音频中是否包含语音活动
        
        Args:
            conn: WebRTC连接对象
            audio: 音频数据
            
        Returns:
            bool: 是否检测到语音活动
        """
        try:
            self._ensure_vad_loaded()
            
            # 首先检查音频数据是否为None
            if audio is None:
                logger.warning("[VAD-DEBUG] 音频数据为None，无法处理")
                return False
                
            # 记录音频信息
            #logger.info(f"[VAD-DEBUG] VAD检测音频，长度: {len(audio)} 字节")
            
            # 检查音频数据完整性
            if len(audio) == 0:
                #logger.warning("[VAD-DEBUG] 音频数据为空")
                return False
                
            # 检查音频数据头部
            #logger.info(f"[VAD-DEBUG] 音频数据头部: {audio[:20]}")
            
            # 检查音频是否是Opus格式
            is_opus = False
            try:
                # Opus帧通常以'OggS'或特定魔术字节开头
                if audio.startswith(b'OggS') or audio.startswith(b'OpusHead'):
                    is_opus = True
                    #logger.info("[VAD-DEBUG] 疑似检测到Opus编码数据")
            except Exception as check_err:
                logger.warning(f"[VAD-DEBUG] 检查音频格式失败: {check_err}")
            
            # 检查音频采样率和格式
            try:
                # 查看连接对象是否有音频格式信息
                if hasattr(conn, 'audio_format'):
                    logger.info(f"[VAD-DEBUG] 连接音频格式: {conn.audio_format}")
                if hasattr(conn, 'sample_rate'):
                    logger.info(f"[VAD-DEBUG] 连接音频采样率: {conn.sample_rate} Hz")
            except Exception as conn_err:
                logger.warning(f"[VAD-DEBUG] 无法获取连接音频配置: {conn_err}")
            
            # 调用VAD判断是否有语音
            # 创建计数器属性，如果不存在
            if not hasattr(self, 'vad_log_counter'):
                self.vad_log_counter = 0
            
            # 每10次输出一次日志
            self.vad_log_counter = (self.vad_log_counter + 1) % 10
            if self.vad_log_counter == 0:
                logger.warning(f"[VAD-DEBUG] 开始调用VAD识别，音频数据长度: {len(audio)} 字节")
                
            is_speech, prob = self.process(audio, conn)
            
            if self.vad_log_counter == 0:
                logger.warning(f"[VAD-DEBUG] VAD检测结果: 有语音活动={is_speech}, 概率: {prob}")
            
            # 更新连接状态
            if is_speech:
                conn.client_have_voice = True
                conn.vad_speech_count = conn.vad_speech_count + 1 if hasattr(conn, 'vad_speech_count') else 1
                #logger.info(f"[VAD-DEBUG] 已设置client_have_voice=True, 连续语音帧计数: {getattr(conn, 'vad_speech_count', 1)}")
            else:
                conn.vad_silence_count = conn.vad_silence_count + 1 if hasattr(conn, 'vad_silence_count') else 1
                #logger.info(f"[VAD-DEBUG] 静音帧计数: {getattr(conn, 'vad_silence_count', 1)}")
                
                # 如果连续静音超过一定阈值，可能声音结束
                if getattr(conn, 'vad_silence_count', 0) > 5 and getattr(conn, 'client_have_voice', False):
                    conn.client_voice_stop = True
                    logger.info("[VAD-DEBUG] 检测到语音结束，已设置client_voice_stop=True")
            
            return is_speech
        except Exception as e:
            #logger.error(f"[VAD-DEBUG] VAD判断出错: {e}")
            logger.error(f"[VAD-DEBUG] 错误详情: {traceback.format_exc()}")
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
        
            # 判断是否为Opus格式
            is_opus = False
            try:
                if audio_data.startswith(b'OggS') or audio_data.startswith(b'OpusHead'):
                    is_opus = True
            except:
                # 如果无法检查前缀，假设不是Opus
                pass
            
            # 如果是PCM数据，进行预处理
            if not is_opus:
                try:
                    # 确保数据长度是2的倍数 (int16 = 2 bytes)
                    buffer_len = len(audio_data)
                    if buffer_len % 2 != 0:
                        audio_data = audio_data[:-1]
                        logger.debug(f"[VAD-DEBUG] 裁剪音频数据以确保长度是2的倍数: {buffer_len} -> {len(audio_data)}")
                    
                    # 简单音频统计分析（仅用于日志）
                    if buffer_len >= 10:  # 确保有足够的数据进行分析
                        data_array = np.frombuffer(audio_data, dtype=np.int16)
                        mean_val = np.mean(np.abs(data_array))
                        
                        # 仅在平均振幅非常低时记录警告
                        if mean_val < 50:  # 降低阈值，减少不必要的警告
                            logger.debug(f"[VAD-DEBUG] 可能为静音数据，平均振幅过低: {mean_val:.2f}")
                except Exception as np_err:
                    logger.debug(f"[VAD-DEBUG] 音频统计分析失败: {np_err}")
            
            # ===== 统一的音频缓冲区管理 =====
            # 初始化音频缓冲区（如果需要）
            if conn:
                if not hasattr(conn, 'audio_buffer'):
                    conn.audio_buffer = {
                        'pcm': [],          # PCM格式数据缓冲区
                        'opus': [],         # Opus格式数据缓冲区（预留）
                        'last_append_time': time.time(),  # 上次添加数据的时间
                        'total_size': 0     # 缓冲区当前总大小
                    }
                
                # 选择正确的缓冲区类型
                buffer_type = 'opus' if is_opus else 'pcm'
                
                # 添加数据到缓冲区并更新元数据
                conn.audio_buffer[buffer_type].append(audio_data)
                conn.audio_buffer['last_append_time'] = time.time()
                conn.audio_buffer['total_size'] = sum(len(segment) for segment in conn.audio_buffer[buffer_type])
                
                total_size = conn.audio_buffer['total_size']
                segments_count = len(conn.audio_buffer[buffer_type])
                
                # 每10个包记录一次缓冲区状态（避免日志过多）
                if segments_count % 10 == 0 or segments_count <= 2:
                    logger.info(f"[VAD-BUFFER] 已累积 {segments_count} 个音频片段，总大小:{total_size}字节")
                
                # 判断是否应该处理缓冲区数据
                process_buffer = False
                process_reason = ""
                
                # 情况1: 缓冲区达到处理阈值
                if total_size >= 6400:  # 6400字节处理阈值
                    process_buffer = True
                    process_reason = "达到处理阈值"
                
                # 情况2: 缓冲区超时（确保音频不会永远积累不处理）
                elif time.time() - conn.audio_buffer['last_append_time'] > 1.5 and segments_count > 0:  # 1.5秒超时
                    process_buffer = True
                    process_reason = "缓冲区超时"
                
                # 如果需要处理缓冲区
                if process_buffer and segments_count > 0:
                    try:
                        # 合并音频数据
                        combined_data = b''.join(conn.audio_buffer[buffer_type])
                        combined_size = len(combined_data)
                        
                        # 记录合并状态
                        logger.info(f"[VAD-PROCESS] {process_reason}，处理缓冲区: {segments_count}个片段，大小{combined_size}字节")
                        
                        # 清空缓冲区
                        conn.audio_buffer[buffer_type] = []
                        conn.audio_buffer['total_size'] = 0
                        conn.audio_buffer['last_append_time'] = time.time()
                        
                        # 调用VAD处理
                        logger.info(f"[VAD-CALL] 调用VAD处理合并音频，数据长度: {combined_size} 字节")
                        is_speech, prob = self.vad.is_speech(combined_data)
                        
                        # 根据处理原因调整返回值
                        if process_reason == "缓冲区超时" and combined_size < 3200:
                            # 对于短音频的超时处理，稍微提高概率以确保短音频能被后续处理
                            logger.info(f"[VAD-RESULT] 超时短音频VAD结果: is_speech={is_speech}, 调整后概率={max(0.4, prob)}")
                            return is_speech, max(0.4, prob)
                        else:
                            logger.info(f"[VAD-RESULT] VAD处理结果: is_speech={is_speech}, 概率={prob}")
                            return is_speech, prob
                    except Exception as e:
                        logger.error(f"[VAD-BUFFER] 音频处理失败: {e}")
                        # 出错时清空缓冲区防止持续累积错误数据
                        conn.audio_buffer[buffer_type] = []
                        conn.audio_buffer['total_size'] = 0
                
                # 如果是新添加的数据（不需要立即处理），返回延迟处理标志
                if not process_buffer:
                    return False, 0.0  # 返回False表示当前未检测到语音，但数据已被累积
            # ===== 如果没有在缓冲区中处理，检查是否需要直接处理 =====
            # 对于大于3200字节的单个数据包或没有连接对象的情况
            if len(audio_data) >= 3200 or not conn:
                # 记录日志（使用计数器减少日志频率）
                if not hasattr(self, 'direct_log_counter'):
                    self.direct_log_counter = 0
                self.direct_log_counter = (self.direct_log_counter + 1) % 10
                
                if self.direct_log_counter == 0:
                    logger.info(f"[VAD-DIRECT] 直接处理大尺寸音频数据，长度: {len(audio_data)} 字节")
                
                # 调用VAD处理
                is_speech, prob = self.vad.is_speech(audio_data)
                
                # 记录结果（使用计数器减少日志频率）
                if self.direct_log_counter == 0:
                    logger.info(f"[VAD-DIRECT-RESULT] VAD结果: is_speech={is_speech}, 概率={prob}")
                
                return is_speech, prob
            
            # 以下情况不应该发生，因为所有情况都应该在上面处理过
            logger.warning(f"[VAD-ERROR] 未预期的处理路径，音频大小: {len(audio_data)} 字节")
            return False, 0.0
        except Exception as e:
            logger.error(f"[VAD-DEBUG] VAD处理错误: {str(e)}")
            logger.error(f"[VAD-DEBUG] 错误详情: {e.__class__.__name__}: {str(e)}")
            logger.error(f"[VAD-DEBUG] 堆栈跟踪: {traceback.format_exc()}")
            return False, 0.0
