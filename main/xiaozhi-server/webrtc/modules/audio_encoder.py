#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
音频编码模块，负责将PCM数据重新编码为Opus格式
"""

import logging
import numpy as np
import opuslib_next
from config.logger import setup_logging
import traceback

logger = setup_logging()

class AudioEncoder:
    """音频编码器，将PCM数据编码为Opus格式"""
    
    def __init__(self, sample_rate=16000, channels=1, frame_size=960):
        """
        初始化Opus编码器
        
        参数:
        sample_rate: 音频采样率，默认16000Hz
        channels: 声道数，默认1（单声道）
        frame_size: 每帧样本数，默认960（60ms @ 16kHz）
        """
        self.sample_rate = sample_rate
        self.channels = channels
        self.frame_size = frame_size
        
        # 初始化Opus编码器
        self.encoder = None
        try:
            self.encoder = opuslib_next.Encoder(sample_rate, channels, 'voip')
            logger.info(f"[AUDIO-ENCODER] Opus编码器初始化成功: {sample_rate}Hz, {channels}通道")
        except Exception as e:
            logger.error(f"[AUDIO-ENCODER] Opus编码器初始化失败: {e}")
    
    def encode_pcm_to_opus(self, pcm_data):
        """
        将PCM数据编码为Opus格式
        
        参数:
        pcm_data: PCM音频数据，可以是bytes或numpy.ndarray
        
        返回:
        bytes: Opus编码数据
        """
        if self.encoder is None:
            logger.error("[AUDIO-ENCODER] 编码器未初始化，无法进行编码")
            return None
            
        try:
            # 处理各种输入格式，转换为numpy数组进行处理
            if isinstance(pcm_data, bytes):
                # 假设字节流是16位整数
                pcm_array = np.frombuffer(pcm_data, dtype=np.int16)
            elif isinstance(pcm_data, np.ndarray):
                pcm_array = pcm_data
                # 如果是浮点数组，转换为16位整数
                if pcm_array.dtype.kind == 'f':
                    pcm_array = (pcm_array * 32767.0).astype(np.int16)
                elif pcm_array.dtype != np.int16:
                    pcm_array = pcm_array.astype(np.int16)
            else:
                logger.error(f"[AUDIO-ENCODER] 不支持的PCM数据类型: {type(pcm_data)}")
                return None
            
            # 检查数据长度是否是frame_size的整数倍
            total_samples = len(pcm_array)
            logger.debug(f"[AUDIO-ENCODER] 输入PCM数据样本数: {total_samples}, 目标帧大小: {self.frame_size}")
            
            # 请求Opus编码器支持的帧大小
            valid_frame_sizes = [120, 240, 480, 960, 1920, 2880]
            if self.frame_size not in valid_frame_sizes:
                # 找到最接近的有效帧大小
                closest_size = min(valid_frame_sizes, key=lambda x: abs(x - self.frame_size))
                logger.warning(f"[AUDIO-ENCODER] 非标准帧大小 {self.frame_size}，调整为 {closest_size}")
                self.frame_size = closest_size
            
            # 确保数据长度与帧大小匹配
            if total_samples < self.frame_size:
                # 数据不足一帧，填充静音
                padding = np.zeros(self.frame_size - total_samples, dtype=np.int16)
                pcm_array = np.concatenate([pcm_array, padding])
                logger.debug(f"[AUDIO-ENCODER] 数据不足一帧，填充至 {self.frame_size} 样本")
            elif total_samples > self.frame_size and total_samples % self.frame_size != 0:
                # 裁剪到帧大小的整数倍
                new_length = (total_samples // self.frame_size) * self.frame_size
                pcm_array = pcm_array[:new_length]
                logger.debug(f"[AUDIO-ENCODER] 裁剪数据长度为 {new_length} 样本")
            
            # 转换为bytes
            pcm_bytes = pcm_array.tobytes()
            
            # 编码为Opus格式
            opus_data = self.encoder.encode(pcm_bytes, self.frame_size)
            logger.debug(f"[AUDIO-ENCODER] PCM数据({len(pcm_bytes)}字节)成功编码为Opus格式({len(opus_data)}字节)")
            return opus_data
            
        except Exception as e:
            logger.error(f"[AUDIO-ENCODER] PCM转Opus编码失败: {e}")
            return None
    
    def __del__(self):
        """析构函数，确保资源被释放"""
        if hasattr(self, 'encoder') and self.encoder:
            self.encoder = None
            logger.debug("[AUDIO-ENCODER] Opus编码器已释放")


# 创建一个全局编码器实例，方便其他模块使用
_global_encoder = None

def get_encoder(sample_rate=16000, channels=1, frame_size=960):
    """获取全局编码器实例"""
    global _global_encoder
    
    # 检查如果已有编码器但参数不匹配，创建新的编码器
    if _global_encoder is None or \
       _global_encoder.sample_rate != sample_rate or \
       _global_encoder.channels != channels or \
       _global_encoder.frame_size != frame_size:
        
        logger.info(f"[AUDIO-ENCODER] 创建新编码器: {sample_rate}Hz, {channels}通道, 帧大小 {frame_size}")
        _global_encoder = AudioEncoder(sample_rate, channels, frame_size)
    
    return _global_encoder

def encode_pcm_to_opus(pcm_data, sample_rate=16000, channels=1, frame_size=960):
    """
    将PCM数据编码为Opus格式的便捷函数
    
    参数:
    pcm_data: PCM音频数据，可以是bytes或numpy.ndarray
    sample_rate: 音频采样率
    channels: 声道数
    frame_size: 每帧样本数
    
    返回:
    bytes: Opus编码数据
    """
    try:
        # Opus支持的采样率: 8000, 12000, 16000, 24000, 48000
        supported_rates = [8000, 12000, 16000, 24000, 48000]
        if sample_rate not in supported_rates:
            closest_rate = min(supported_rates, key=lambda x: abs(x - sample_rate))
            logger.warning(f"[AUDIO-ENCODER] 不支持的采样率 {sample_rate}Hz，使用最接近的 {closest_rate}Hz")
            sample_rate = closest_rate
        
        # 对于48kHz的采样率，帧大小应该为960/1920/2880
        if sample_rate == 48000:
            valid_sizes = [120, 240, 480, 960, 1920, 2880]
            if frame_size not in valid_sizes:
                # 为48kHz选择适当的帧大小
                if frame_size > 1920:
                    frame_size = 1920
                elif frame_size > 960:
                    frame_size = 960
                else:
                    frame_size = 480
                
        # 获取编码器并进行编码
        encoder = get_encoder(sample_rate, channels, frame_size)
        return encoder.encode_pcm_to_opus(pcm_data)
    except Exception as e:
        logger.error(f"[AUDIO-ENCODER] PCM转换为Opus失败: {e}")
        return None
