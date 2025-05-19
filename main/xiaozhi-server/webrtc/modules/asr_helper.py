#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
ASR辅助模块
负责语音识别(ASR)功能的处理
"""

import logging
import traceback

logger = logging.getLogger(__name__)

class ASRHelper:
        def __init__(self):
            # 使用全局日志对象
            self.logger = logger
        
        async def speech_to_text(self, audio_data, session_id):
            """异步处理语音转文本
            
            Args:
                audio_data: 音频数据列表，每个元素是一个OPUS编码的音频数据包
                session_id: 会话标识
                
            Returns:
                tuple: (text, extra_info)返回识别文本和额外信息
            """
            try:
                # 使用配置文件获取全局ASR服务
                from config.config_loader import load_config
                config = load_config()
                
                # 使用正确的方式获取ASR服务
                from core.utils.util import initialize_modules
                
                # 尝试初始化ASR模块
                modules = initialize_modules(self.logger, config, init_asr=True)
                asr_provider = modules.get("asr")
                
                if asr_provider is None:
                    # 如果无法通过initialize_modules获取，尝试直接创建ASR服务
                    from core.providers.asr.doubao import ASRProvider
                    select_asr_module = config["selected_module"]["ASR"]
                    asr_config = config["ASR"][select_asr_module]
                    asr_provider = ASRProvider(asr_config, False)
                
                self.logger.warning(f"[SERVER-ASR] 获取到ASR服务: {type(asr_provider).__name__}")
                
                # 调用ASR服务进行语音识别
                # 注意：asr_provider.speech_to_text是异步方法，返回(text, extra_info)
                text, extra_info = await asr_provider.speech_to_text(audio_data, session_id)
                
                # 在日志中记录识别结果
                if text and len(text.strip()) > 0:
                    self.logger.warning(f"[SERVER-ASR] 识别成功: '{text}'")
                else:
                    self.logger.warning(f"[SERVER-ASR] 识别为空或失败")
                    text = ""
                    extra_info = {}
                
                return text, extra_info
            except Exception as e:
                stack_trace = traceback.format_exc()
                self.logger.error(f"[SERVER-ASR] ASR处理异常: {e}\n{stack_trace}")
                return "", {}
