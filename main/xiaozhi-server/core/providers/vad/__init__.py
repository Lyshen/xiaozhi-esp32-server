#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
VAD提供者模块初始化
"""

import logging
from config.config_loader import load_config
from core.providers.vad.silero import VADProvider

logger = logging.getLogger(__name__)

class VADProviderAdapter:
    """VAD提供者适配器，用于统一接口"""
    
    def __init__(self, vad_provider):
        self.vad_provider = vad_provider
        
    def is_vad(self, conn, audio):
        return self.vad_provider.is_vad(conn, audio)
        
    def is_speech(self, audio_data):
        """适配is_speech接口，调用is_vad方法"""
        # 没有连接对象，创建一个模拟对象
        class MockConn:
            def __init__(self):
                self.client_audio_buffer = bytearray()
                self.client_have_voice = False
                
        mock_conn = MockConn()
        result = self.vad_provider.is_vad(mock_conn, audio_data)
        # is_vad返回的是布尔值，需要返回(is_speech, probability)元组
        return result, 1.0 if result else 0.0

def get_vad_provider():
    """
    获取VAD提供者实例
    
    Returns:
        VADProvider: VAD提供者实例
    """
    try:
        # 加载配置
        config = load_config()
        
        # 获取VAD配置
        selected_vad = config.get('selected_module', {}).get('VAD', 'silero')
        vad_config = config.get('VAD', {}).get(selected_vad, {})
        
        # 添加默认配置
        if 'model_dir' not in vad_config:
            vad_config['model_dir'] = 'models/silero_vad'
        
        if 'threshold' not in vad_config:
            vad_config['threshold'] = 0.5
            
        # 创建VAD提供者实例并包装成适配器
        logger.info(f"初始化VAD提供者: {selected_vad}, 配置: {vad_config}")
        vad_provider = VADProvider(vad_config)
        return VADProviderAdapter(vad_provider)
    except Exception as e:
        logger.error(f"初始化VAD提供者失败: {e}")
        raise
