#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
VAD辅助模块
负责语音活动检测(Voice Activity Detection)功能
"""

import logging
import time

logger = logging.getLogger(__name__)


class VADHelper:
        def __init__(self, logger):
            self.logger = logger
            
        def process(self, audio_segment):
            # 返回值：(is_speech, probability)
            try:
                from core.media.webrtc_vad_processor import process_frame_with_vad
                return process_frame_with_vad(audio_segment)
            except ImportError:
                # 如果无法导入，默认判断为有语音
                return (True, 0.9)
                
        def is_vad(self, conn, audio):
            """与原有的VAD处理兼容的方法"""
            self.logger.warning(f"[SERVER-AUDIO] VAD检测音频，长度: {len(audio)} 字节")
            
            try:
                # 尝试调用process方法进行检测
                is_speech, prob = self.process(audio)
                
                # 设置已有语音标志
                if is_speech:
                    conn.client_have_voice = True
                    self.logger.warning(f"[SERVER-AUDIO] VAD检测结果: 有语音活动，概率: {prob}")
                    
                    # 如果有语音，记录最后时间
                    conn.client_have_voice_last_time = time.time() * 1000
                    return True
                else:
                    # 判断是否语音结束
                    if conn.client_have_voice:
                        # 如果之前有语音，还需要检查是否真的停止
                        current_time = time.time() * 1000
                        time_since_last_voice = current_time - conn.client_have_voice_last_time
                        
                        # 如果没有语音的时间超过500ms，认为语音停止
                        if time_since_last_voice > 500:
                            conn.client_voice_stop = True
                            self.logger.warning(f"[SERVER-AUDIO] VAD检测到语音停止，无语音时间: {time_since_last_voice}ms")
                    
                    self.logger.warning(f"[SERVER-AUDIO] VAD检测结果: 无语音活动，概率: {prob}")
                    return False
            except Exception as e:
                # 遇到异常则返回当前状态
                self.logger.error(f"[SERVER-AUDIO-ERROR] VAD检测异常: {e}")
                return conn.client_have_voice
