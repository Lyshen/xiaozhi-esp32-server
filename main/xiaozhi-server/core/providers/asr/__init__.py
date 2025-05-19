#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
ASR提供者模块初始化
"""

import logging
from config.config_loader import load_config

logger = logging.getLogger(__name__)

def get_asr_provider():
    """
    获取ASR提供者实例
    
    Returns:
        ASRProvider: ASR提供者实例
    """
    try:
        # 加载配置
        config = load_config()
        
        # 获取ASR配置
        selected_asr = config.get('selected_module', {}).get('ASR', 'doubao')
        asr_config = config.get('ASR', {}).get(selected_asr, {})
        
        # 根据选定的ASR模块导入相应的提供者
        if selected_asr == 'doubao':
            from core.providers.asr.doubao import ASRProvider
        elif selected_asr == 'fun_local':
            from core.providers.asr.fun_local import ASRProvider
        elif selected_asr == 'sherpa_onnx_local':
            from core.providers.asr.sherpa_onnx_local import ASRProvider
        elif selected_asr == 'tencent':
            from core.providers.asr.tencent import ASRProvider
        else:
            # 默认使用doubao
            from core.providers.asr.doubao import ASRProvider
            selected_asr = 'doubao'
            
        # 创建ASR提供者实例
        logger.info(f"初始化ASR提供者: {selected_asr}, 配置: {asr_config}")
        return ASRProvider(asr_config, False)
    except Exception as e:
        logger.error(f"初始化ASR提供者失败: {e}")
        raise
