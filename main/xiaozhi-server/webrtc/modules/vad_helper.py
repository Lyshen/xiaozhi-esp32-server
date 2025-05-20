#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
VAD辅助模块
负责语音活动检测(Voice Activity Detection)功能
"""

import logging
import traceback
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
            
            # 每100次输出一次日志
            self.vad_log_counter = (self.vad_log_counter + 1) % 100
            if self.vad_log_counter == 0:
                logger.warning(f"[VAD-DEBUG] 开始调用VAD识别")
                
            is_speech, prob = self.process(audio)
            
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
    
    def process(self, audio_data):
        """
        处理音频数据，检测是否有语音活动
        
        Args:
            audio_data: 音频数据（可能是PCM或Opus格式）
            
        Returns:
            tuple: (is_speech, probability)
        """
        try:
            self._ensure_vad_loaded()
            
            # 记录音频数据信息
            #logger.info(f"[VAD-DEBUG] 处理音频数据: 长度={len(audio_data)}字节, 前10字节={audio_data[:10]}")
            
            # 判断是否为Opus格式
            is_opus = False
            try:
                if audio_data.startswith(b'OggS') or audio_data.startswith(b'OpusHead'):
                    is_opus = True
                    #logger.info("[VAD-DEBUG] 检测到Opus格式数据")
            except:
                # 如果无法检查前缀，假设不是Opus
                pass
                
            # 如果是PCM数据，进行统计分析
            if not is_opus:
                try:
                    # 简单检查是否是可能的PCM数据
                    data_array = np.frombuffer(audio_data, dtype=np.int16)
                    mean_val = np.mean(np.abs(data_array))
                    std_val = np.std(data_array)
                    #logger.info(f"[VAD-DEBUG] 音频统计: 平均振幅={mean_val:.2f}, 标准差={std_val:.2f}")
                    
                    # 检查是否为静音
                    if mean_val < 100:  # 阈值可能需要调整
                        logger.warning(f"[VAD-DEBUG] 可能为静音数据，平均振幅过低: {mean_val:.2f}")
                except Exception as np_err:
                    logger.warning(f"[VAD-DEBUG] 音频统计分析失败: {np_err}")
            
            # 如果音频数据太短，可能无法进行VAD判断
            if len(audio_data) < 320 and not is_opus:  # 仅对PCM数据做长度检查
                logger.warning(f"[VAD-DEBUG] 音频数据太短: {len(audio_data)}字节")
                return False, 0.0
                
            # VAD处理 - 使用原始接口，不添加额外参数
            is_speech, prob = self.vad.is_speech(audio_data)
            
            # 创建计数器属性，如果不存在
            if not hasattr(self, 'process_log_counter'):
                self.process_log_counter = 0
            
            # 每100次输出一次日志
            self.process_log_counter = (self.process_log_counter + 1) % 100
            if self.process_log_counter == 0:
                logger.info(f"[VAD-DEBUG] VAD结果: is_speech={is_speech}, 概率={prob}")
                
            return is_speech, prob
        except Exception as e:
            logger.error(f"[VAD-DEBUG] VAD处理错误: {str(e)}")
            logger.error(f"[VAD-DEBUG] 错误详情: {e.__class__.__name__}: {str(e)}")
            logger.error(f"[VAD-DEBUG] 堆栈跟踪: {traceback.format_exc()}")
            return False, 0.0
