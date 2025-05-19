#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
WebRTC连接模块
定义WebRTC连接类及其相关功能
"""

import copy
import logging
import time
import traceback
from concurrent.futures import ThreadPoolExecutor

from .asr_helper import ASRHelper
from .vad_helper import VADHelper

logger = logging.getLogger(__name__)

class WebRTCConnection:
    def __init__(self, client_id):
        # 从默认配置中导入基本配置
        from config.config_loader import load_config
        default_config = load_config()
        self.config = copy.deepcopy(default_config)
        
        # 基本识别属性
        self.client_id = client_id
        self.headers = {"device-id": client_id}
        self.session_id = f"webrtc_{client_id}"
        
        # VAD相关属性 - process_audio_internal所需
        self.client_audio_buffer = bytearray()
        self.client_listen_mode = "auto"
        self.client_have_voice = False
        self.client_voice_stop = False
        self.client_voice_stop_requested = False  # 新增：标记用户通过WebSocket请求停止（Push-to-Talk按钮释放）
        self.client_abort = False
        self.client_no_voice_last_time = 0.0
        
        # ASR相关属性 - process_audio_internal所需
        self.asr_server_receive = True  # 确保设置这个属性以避免AttributeError
        self.asr_audio = []  # 用于存储音频数据
        
        # 聊天和线程相关属性
        self.executor = ThreadPoolExecutor(max_workers=2)
        self.stop_event = asyncio.Event()
        self.audio_play_queue = asyncio.Queue()
        self.tts_queue = asyncio.Queue()
        self.llm_finish_task = False
        self.tts_first_text_index = 0
        self.tts_last_text_index = 0
        self.websocket = None
        
        # 退出命令配置
        self.cmd_exit = self.config.get("exit_commands", ["再见", "拜拜", "退出"])
        
        # 意图和功能相关属性
        self.use_function_call_mode = self.config.get("use_function_call_mode", False)
        try:
            from core.handle.functionHandler import FunctionHandler
            self.func_handler = FunctionHandler(self)
        except ImportError:
            self.func_handler = None
        
        # 其他属性
        self.use_webrtc = True
        self.need_bind = False
        self.max_output_size = 0
        self.close_after_chat = False
        self.prompt = self.config.get("prompt", "你是小智")
        self.welcome_msg = {"type": "welcome", "device-id": client_id}
        
        # 对话历史
        try:
            from core.utils.dialogue import Dialogue
            self.dialogue = Dialogue()
        except ImportError:
            self.dialogue = None
            
        # 辅助方法
        self.recode_first_last_text = self.record_text_index
        
        # 创建模拟的VAD和ASR对象
        self.vad = self.VADHelper(logger)
        self.asr = self.ASRHelper()
    
    # 内部辅助类 - ASR处理器

    
    def record_text_index(self, text, text_index=0):
        """记录大模型输出文本的首尾索引"""
        if self.tts_first_text_index == 0 and text_index > 0:
            logging.info(f"大模型说出第一句话: {text}")
            self.tts_first_text_index = text_index
        self.tts_last_text_index = text_index
        return text_index
        
    def speak_and_play(self, text, text_index=0):
        """转换和准备音频播放"""
        if text is None or len(text) <= 0:
            logging.info(f"无需tts转换，文本为空")
            return None, text, text_index
            
        try:
            # 尝试从应用上下文获取TTS服务
            tts_service = None
            if hasattr(self, 'app_context') and self.app_context:
                tts_service = getattr(self.app_context, 'tts', None)
            
            if not tts_service:
                from core.providers.tts.doubao import DoubaoTTS
                tts_service = DoubaoTTS()
                
            tts_file = tts_service.to_tts(text)
            if tts_file is None:
                logging.error(f"tts转换失败，{text}")
                return None, text, text_index
                
            logging.debug(f"TTS 文件生成完毕: {tts_file}")
            return tts_file, text, text_index
        except Exception as e:
            logging.error(f"TTS处理异常: {e}")
            return None, text, text_index
        
    def should_replace_opus(self):
        return True
    
    def reset_vad_states(self):
        """重置VAD状态"""
        self.client_have_voice = False
        self.client_voice_stop = False
        self.client_voice_stop_requested = False  # 重置Push-to-Talk请求标志
        logger.warning(f"[SERVER-AUDIO] VAD状态已重置: have_voice={self.client_have_voice}, voice_stop={self.client_voice_stop}, stop_requested={self.client_voice_stop_requested}")
    
    async def chat(self, text):
        """实现常规聊天功能"""
        logging.info(f"[WEBRTC-CHAT] 进入常规聊天模式, 文本: {text}")
        try:
            # 尝试从应用上下文获取LLM服务
            llm_service = None
            if hasattr(self, 'app_context') and self.app_context:
                llm_service = getattr(self.app_context, 'llm', None)
            
            if not llm_service:
                from core.providers.llm.ali import AliLLM
                llm_service = AliLLM()
                
            # 添加用户消息到对话历史
            if self.dialogue:
                from core.utils.dialogue import Message
                self.dialogue.put(Message(role="user", content=text))
                
            # 提供对话历史进行语言模型调用
            response = llm_service.generate(self.dialogue.dialogue, system_prompt=self.prompt)
            logging.info(f"[WEBRTC-CHAT] 语言模型响应: {response}")
            
            # 添加响应到对话历史
            if self.dialogue:
                self.dialogue.put(Message(role="assistant", content=response))
            
            # 生成语音并准备播放
            text_index = self.tts_last_text_index + 1
            self.recode_first_last_text(response, text_index)
            tts_data = self.speak_and_play(response, text_index)
            
            # 标记任务完成
            self.llm_finish_task = True
            
            # 返回响应
            return response
            
        except Exception as e:
            logging.error(f"[WEBRTC-CHAT-ERROR] 聊天处理异常: {e}")
            return "抱歉，我遇到了一些问题，请稍后再试。"
        
    async def chat_with_function_calling(self, text):
        """实现基于function calling的聊天"""
        logging.info(f"[WEBRTC-CHAT] 进入function calling聊天模式, 文本: {text}")
        try:
            # 确保我们有function handler
            if not hasattr(self, 'func_handler') or not self.func_handler:
                logging.warning("[WEBRTC-CHAT] 未找到function handler，回退到常规聊天模式")
                return await self.chat(text)
                
            # 尝试从应用上下文获取LLM服务
            llm_service = None
            if hasattr(self, 'app_context') and self.app_context:
                llm_service = getattr(self.app_context, 'llm', None)
            
            if not llm_service:
                from core.providers.llm.ali import AliLLM
                llm_service = AliLLM()
                
            # 添加用户消息到对话历史
            if self.dialogue:
                from core.utils.dialogue import Message
                self.dialogue.put(Message(role="user", content=text))
                
            # 提供对话历史和函数定义进行语言模型调用
            import json
            import uuid
            
            # 获取可用函数列表
            functions = self.func_handler.get_function_descriptions()
            
            # 调用语言模型并检查函数调用
            response = llm_service.generate_with_functions(
                self.dialogue.dialogue, 
                functions=functions,
                system_prompt=self.prompt
            )
            
            # 处理响应
            if isinstance(response, dict) and 'function_call' in response:
                # 这是一个函数调用
                function_name = response['function_call']['name']
                logging.info(f"[WEBRTC-CHAT] 识别出函数调用: {function_name}")
                
                # 如果是继续对话函数，返回常规对话
                if function_name == "continue_chat":
                    return await self.chat(text)
                    
                # 准备函数参数
                function_args = response['function_call'].get('arguments', '{}')
                if isinstance(function_args, dict):
                    function_args = json.dumps(function_args)
                    
                # 创建函数调用数据
                function_call_data = {
                    "name": function_name,
                    "id": str(uuid.uuid4().hex),
                    "arguments": function_args
                }
                
                # 执行函数调用
                result = self.func_handler.handle_llm_function_call(self, function_call_data)
                
                # 处理函数返回结果
                if result:
                    response_text = result.response or result.result
                    if response_text:
                        # 生成语音并准备播放
                        text_index = self.tts_last_text_index + 1
                        self.recode_first_last_text(response_text, text_index)
                        tts_data = self.speak_and_play(response_text, text_index)
                        
                        # 添加到对话历史
                        if self.dialogue:
                            self.dialogue.put(Message(role="assistant", content=response_text))
                return result
            else:
                # 常规文本响应
                logging.info(f"[WEBRTC-CHAT] 语言模型文本响应: {response}")
                
                # 添加响应到对话历史
                if self.dialogue:
                    self.dialogue.put(Message(role="assistant", content=response))
                
                # 生成语音并准备播放
                text_index = self.tts_last_text_index + 1
                self.recode_first_last_text(response, text_index)
                tts_data = self.speak_and_play(response, text_index)
                
                # 返回响应文本
                return response
                
        except Exception as e:
            logging.error(f"[WEBRTC-CHAT-ERROR] Function calling聊天处理异常: {e}")
            import traceback
            logging.error(f"[WEBRTC-CHAT-ERROR] 异常详情: {traceback.format_exc()}")
            return "抱歉，我在处理您的请求时遇到了问题。"