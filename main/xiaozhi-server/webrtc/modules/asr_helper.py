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
            
            # 记录ASR配置信息
            asr_config = config.get('ASR', {})
            logger.info(f"[ASR-DEBUG] ASR配置信息: {asr_config.keys()}")
            selected_module = config.get('selected_module', {}).get('ASR')
            logger.info(f"[ASR-DEBUG] 选择的ASR模块: {selected_module}")
            
            # 检查音频数据
            total_audio_segments = len(audio_data) if audio_data else 0
            total_audio_bytes = sum(len(segment) for segment in audio_data if segment)
            logger.info(f"[ASR-DEBUG] 即将处理的音频数据: {total_audio_segments}段, 总计{total_audio_bytes}字节")
            
            # 记录音频段大小分布
            if total_audio_segments > 0 and total_audio_bytes > 0:
                segment_sizes = [len(segment) for segment in audio_data if segment]
                size_info = segment_sizes[:5] if len(segment_sizes) > 5 else segment_sizes
                logger.info(f"[ASR-DEBUG] 音频片段大小分布: {size_info}" + 
                         (f" ..." if len(segment_sizes) > 5 else ""))
                
                # 检查第一段音频数据
                if segment_sizes and segment_sizes[0] > 0 and audio_data[0]:
                    first_bytes = audio_data[0][:20]
                    logger.info(f"[ASR-DEBUG] 第一段音频数据头部字节: {first_bytes}")
            else:
                logger.warning(f"[ASR-DEBUG] 音频数据为空或无效")
                return "", {}
            
            # 使用正确的方式获取ASR服务
            from core.utils.util import initialize_modules
            
            # 尝试初始化ASR模块
            logger.info(f"[ASR-DEBUG] 尝试初始化ASR模块")
            modules = initialize_modules(self.logger, config, init_asr=True)
            asr_provider = modules.get("asr")
            
            if asr_provider is None:
                logger.warning(f"[ASR-DEBUG] 通过initialize_modules无法获取ASR服务，尝试备选方法")
                # 如果无法通过initialize_modules获取，尝试直接创建ASR服务
                try:
                    from core.providers.asr.doubao import ASRProvider
                    select_asr_module = config["selected_module"]["ASR"]
                    asr_config = config["ASR"][select_asr_module]
                    asr_provider = ASRProvider(asr_config, False)
                    logger.info(f"[ASR-DEBUG] 成功创建ASR服务: {asr_provider.__class__.__name__}")
                except Exception as asr_init_error:
                    logger.error(f"[ASR-DEBUG] ASR服务创建失败: {asr_init_error}")
                    return "", {}
            
            self.logger.warning(f"[SERVER-ASR] 获取到ASR服务: {type(asr_provider).__name__}")
            
            # 调用ASR服务进行语音识别
            logger.info(f"[ASR-DEBUG] 开始调用ASR服务, 会话ID: {session_id}")
            text, extra_info = await asr_provider.speech_to_text(audio_data, session_id)
            
            # 在日志中记录识别结果
            if text and len(text.strip()) > 0:
                self.logger.warning(f"[SERVER-ASR] 识别成功: '{text}'")
                logger.info(f"[ASR-DEBUG] ASR返回结果额外信息: {extra_info}")
            else:
                self.logger.warning(f"[SERVER-ASR] 识别为空或失败")
                logger.info(f"[ASR-DEBUG] ASR失败原因: {extra_info}")
                text = ""
                extra_info = {}
            
            return text, extra_info
        except Exception as e:
            stack_trace = traceback.format_exc()
            self.logger.error(f"[SERVER-ASR] ASR处理异常: {e}")
            logger.error(f"[ASR-DEBUG] 错误详情: {e.__class__.__name__}: {str(e)}")
            logger.error(f"[ASR-DEBUG] 堆栈跟踪: {stack_trace}")
            return "", {}
