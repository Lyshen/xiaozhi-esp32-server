#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
WebRTC连接管理器
负责创建、管理和维护WebRTC连接
"""

import asyncio
import json
import logging
import time
import weakref
import copy
import queue
import traceback
from concurrent.futures import ThreadPoolExecutor
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer
from aiortc.contrib.media import MediaStreamTrack
import av

logger = logging.getLogger(__name__)

class AudioTrackProcessor(MediaStreamTrack):
    """处理音频轨道的MediaStreamTrack子类"""
    
    kind = "audio"  # MediaStreamTrack类型
    
    def __init__(self, track, on_frame=None):
        """
        初始化音频处理器
        
        Args:
            track: 源音频轨道
            on_frame: 处理音频帧的回调函数
        """
        super().__init__()
        self.track = track
        self.on_frame = on_frame
        self._queue = asyncio.Queue()
        self._start = None
        
    async def recv(self):
        """
        接收音频帧
        
        Returns:
            av.AudioFrame: 处理后的音频帧
        """
        frame = await self.track.recv()
        
        # 如果有回调函数，处理音频帧
        if self.on_frame:
            await self.on_frame(frame)
            
        # 返回处理后的帧
        return frame


# 创建一个持久化的WebRTC连接类，用于存储VAD和ASR状态
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
        
    # 内部辅助类 - VAD处理器
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
    
    # 内部辅助类 - ASR处理器
    class ASRHelper:
        def __init__(self):
            self.logger = logging.getLogger(__name__)
        
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
        
        self.vad = VADHelper(logger)
        
        # 创建一个模拟的ASR对象
        class ASRHelper:
            async def speech_to_text(self, audio_data, session_id):
                logger.warning(f"[SERVER-AUDIO] ASR处理音频，收到 {len(audio_data)} 段音频数据")
                # 实际处理音频的地方
                if len(audio_data) > 0:
                    total_bytes = sum(len(a) for a in audio_data if a is not None)
                    logger.warning(f"[SERVER-AUDIO] ASR处理音频总长度: {total_bytes} 字节")
                    return "WebRTC音频转写测试成功", None
                else:
                    logger.warning(f"[SERVER-AUDIO] ASR收到空音频数据")
                    return "", None
        
        self.asr = ASRHelper()
        logger.warning(f"[SERVER-AUDIO] WebRTCConnection对象创建完成，客户端ID: {client_id}")
    
    def should_replace_opus(self):
        return True
    
    def reset_vad_states(self):
        logger.warning(f"[SERVER-AUDIO] 重置VAD状态")
        self.client_have_voice = False
        self.client_voice_stop = False
        logger.warning(f"[SERVER-AUDIO] VAD状态已重置: have_voice={self.client_have_voice}, voice_stop={self.client_voice_stop}")
    
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


class ConnectionManager:
    """WebRTC连接管理器，负责处理和维护WebRTC连接"""
    
    def __init__(self, config):
        """
        初始化连接管理器
        
        Args:
            config: WebRTC配置对象
        """
        self.config = config
        self.peer_connections = {}  # client_id -> RTCPeerConnection
        self.data_channels = {}     # client_id -> RTCDataChannel  
        self.audio_processors = {}  # client_id -> AudioTrackProcessor
        self.pending_candidates = {}  # client_id -> [candidates]
        
        # 存储客户端的音频处理统计信息
        self.client_stats = {}  # client_id -> stats dict
        
        # 持久化的WebRTC连接对象
        self.webrtc_connections = {}  # client_id -> WebRTCConnection
        
        # 音频帧计数器
        self.audio_packet_counters = {}
        self.audio_bytes_counters = {}
        self.last_log_time = {}
        
        # 创建RTCConfiguration，包含ICE服务器
        ice_servers = [RTCIceServer(**server) for server in config.get_ice_servers()]
        self.rtc_configuration = RTCConfiguration(ice_servers)
        
        logger.info(f"WebRTC连接管理器初始化，ICE服务器数量: {len(ice_servers)}")
    
    async def create_peer_connection(self, client_id):
        """
        为客户端创建新的对等连接
        
        Args:
            client_id: 客户端ID
            
        Returns:
            RTCPeerConnection: 创建的对等连接
        """
        # 如果已存在，先关闭旧连接
        if client_id in self.peer_connections:
            await self.close_connection(client_id)
            
        # 创建新连接
        pc = RTCPeerConnection(configuration=self.rtc_configuration)
        self.peer_connections[client_id] = pc
        
        # 设置ICE连接状态变化回调
        @pc.on("iceconnectionstatechange")
        async def on_iceconnectionstatechange():
            logger.info(f"ICE连接状态变化 [客户端: {client_id}]: {pc.iceConnectionState}")
            if pc.iceConnectionState == "connected":
                logger.info(f"WebRTC: ICE连接已成功建立 [客户端: {client_id}]")
            elif pc.iceConnectionState == "completed":
                logger.info(f"WebRTC: ICE连接已完成并稳定 [客户端: {client_id}]")
            elif pc.iceConnectionState == "failed":
                logger.info(f"WebRTC: ICE连接失败 [客户端: {client_id}]")
                await self.handle_connection_failure(client_id)
        
        # 设置数据通道回调
        @pc.on("datachannel")
        def on_datachannel(channel):
            channel_id = channel.label
            logger.info(f"数据通道已创建 [客户端: {client_id}, 通道: {channel_id}]")
            self.data_channels[f"{client_id}_{channel_id}"] = channel
            
            @channel.on("message")
            def on_message(message):
                if isinstance(message, str):
                    try:
                        data = json.loads(message)
                        logger.info(f"收到数据通道消息 [客户端: {client_id}, 通道: {channel_id}]: {data}")
                    except json.JSONDecodeError:
                        logger.info(f"收到数据通道消息 [客户端: {client_id}, 通道: {channel_id}]: {message}")
                else:
                    logger.info(f"收到数据通道二进制消息 [客户端: {client_id}, 通道: {channel_id}]: {len(message)} 字节")
        
        # 设置音频/视频轨道回调
        @pc.on("track")
        def on_track(track):
            if track.kind == "audio":
                logger.info(f"收到音频轨道 [客户端: {client_id}]")
                
                # 创建处理音频帧的回调函数
                async def frame_callback(frame):
                    try:
                        # 处理音频帧
                        await self.process_audio_frame(frame, client_id)
                    except Exception as e:
                        logger.error(f"处理音频帧时出错: {e}")
                        import traceback
                        logger.error(f"堆栈跟踪: {traceback.format_exc()}")
                
                # 创建音频处理器
                processor = AudioTrackProcessor(track, on_frame=frame_callback)
                self.audio_processors[client_id] = processor
                
                # 返回处理后的轨道
                return processor
            elif track.kind == "video":
                logger.info(f"收到视频轨道 [客户端: {client_id}]")
                # 不处理视频轨道，直接返回
                return track
        
        return pc
    
    async def handle_offer(self, client_id, offer_data, websocket=None):
        """
        处理客户端发送的Offer
        
        Args:
            client_id: 客户端ID
            offer_data: Offer数据
            websocket: WebSocket连接
        """
        logger.info(f"接收Offer [客户端: {client_id}]")
        
        # 1. 提取SDP信息
        try:
            # 处理不同格式的offer_data
            if isinstance(offer_data, dict):
                # 如果offer_data是字典，尝试获取sdp字段
                offer_sdp = offer_data.get("sdp", {})
                if isinstance(offer_sdp, dict):
                    # 如果offset_sdp是字典，直接获取type和sdp
                    type_ = offer_sdp.get("type")
                    sdp = offer_sdp.get("sdp")
                elif isinstance(offer_sdp, str):
                    # 如果offset_sdp是字符串，将其作为sdp值，type设为"offer"
                    type_ = "offer"
                    sdp = offer_sdp
                else:
                    logger.error(f"无法解析的offer_sdp格式: {type(offer_sdp)} [客户端: {client_id}]")
                    return
            elif isinstance(offer_data, str):
                # 如果offer_data是字符串，直接将其作为sdp值，type设为"offer"
                type_ = "offer"
                sdp = offer_data
            else:
                logger.error(f"无法解析的offer_data格式: {type(offer_data)} [客户端: {client_id}]")
                return
                
            if not type_ or not sdp:
                logger.error(f"无效的Offer格式 [客户端: {client_id}]")
                return
            
            # 2. 创建RTCSessionDescription
            offer = RTCSessionDescription(sdp=sdp, type=type_)
            
            # 3. 创建PeerConnection
            pc = await self.create_peer_connection(client_id)
            
            # 4. 设置远程描述（Offer）
            await pc.setRemoteDescription(offer)
            
            # 5. 创建Answer
            answer = await pc.createAnswer()
            
            # 6. 设置本地描述（Answer）
            await pc.setLocalDescription(answer)
            
            # 7. 发送Answer给客户端
            answer_data = {
                "type": "answer",
                "sdp": {
                    "type": pc.localDescription.type,
                    "sdp": pc.localDescription.sdp
                },
                "client_id": client_id
            }
            
            # 通过信令通道发送Answer
            if websocket and websocket.open:
                await websocket.send(json.dumps(answer_data))
                logger.info(f"发送Answer [客户端: {client_id}]")
            else:
                logger.warning(f"无法发送Answer，WebSocket连接不可用 [客户端: {client_id}]")
            
            # 8. 如果有待处理的ICE候选者，添加它们
            if client_id in self.pending_candidates:
                for candidate_data in self.pending_candidates[client_id]:
                    await self.handle_ice_candidate(client_id, candidate_data)
                # 清空待处理的候选者
                self.pending_candidates.pop(client_id, None)
                
        except Exception as e:
            logger.error(f"处理Offer时出错 [客户端: {client_id}]: {e}")
            import traceback
            logger.error(f"堆栈跟踪: {traceback.format_exc()}")
    
    async def handle_answer(self, client_id, answer_data):
        """
        处理客户端发送的Answer
        
        Args:
            client_id: 客户端ID
            answer_data: Answer数据
        """
        logger.info(f"收到Answer [客户端: {client_id}]")
        
        pc = self.peer_connections.get(client_id)
        if not pc:
            logger.warning(f"未找到对应的PeerConnection [客户端: {client_id}]")
            return
            
        # 1. 提取SDP信息
        try:
            answer_sdp = answer_data.get("sdp", {})
            type_ = answer_sdp.get("type")
            sdp = answer_sdp.get("sdp")
            
            if not type_ or not sdp:
                logger.error(f"无效的Answer格式 [客户端: {client_id}]")
                return
                
            # 2. 创建RTCSessionDescription
            answer = RTCSessionDescription(sdp=sdp, type=type_)
            
            # 3. 设置远程描述（Answer）
            await pc.setRemoteDescription(answer)
            logger.info(f"设置远程描述成功 [客户端: {client_id}]")
            
        except Exception as e:
            logger.error(f"处理Answer时出错 [客户端: {client_id}]: {e}")
            import traceback
            logger.error(f"堆栈跟踪: {traceback.format_exc()}")
    
    async def handle_ice_candidate(self, client_id: str, candidate_data: dict):
        """
        处理ICE候选者
        
        Args:
            client_id: 客户端ID
            candidate_data: ICE候选者数据
        """
        # 获取对应的PeerConnection
        pc = self.peer_connections.get(client_id)
        
        # 如果没有找到对应的PeerConnection，则缓存候选者
        if not pc:
            if client_id not in self.pending_candidates:
                self.pending_candidates[client_id] = []
            self.pending_candidates[client_id].append(candidate_data)
            logger.info(f"缓存ICE候选者 [客户端: {client_id}]")
            return
            
        # 从候选者数据中提取信息
        try:
            ice_candidate = candidate_data.get("candidate", {})
            candidate = ice_candidate.get("candidate", "")
            sdpMid = ice_candidate.get("sdpMid", "")
            sdpMLineIndex = ice_candidate.get("sdpMLineIndex", 0)
            
            if candidate:
                # 创建RTCIceCandidate并添加到PeerConnection
                await pc.addIceCandidate({
                    "candidate": candidate,
                    "sdpMid": sdpMid,
                    "sdpMLineIndex": sdpMLineIndex
                })
                logger.info(f"添加ICE候选者成功 [客户端: {client_id}]")
            else:
                logger.warning(f"空的ICE候选者 [客户端: {client_id}]")
                
        except Exception as e:
            logger.error(f"处理ICE候选者时出错 [客户端: {client_id}]: {e}")
            import traceback
            logger.error(f"堆栈跟踪: {traceback.format_exc()}")
    
    async def process_audio(self, client_id, audio_data):
        """
        处理客户端发送的音频数据
        
        Args:
            client_id: 客户端ID
            audio_data: 音频数据
        """
        logger.debug(f"处理音频数据 [客户端: {client_id}], 大小: {len(audio_data)} 字节")
        
        # TODO: 实现音频处理逻辑
        
    async def _convert_audio_to_pcm(self, frame):
        """将音频帧转换为PCM格式"""
        # 使用PyAV将音频帧转换为NumPy数组，再转为bytes
        ndarray = frame.to_ndarray()
        return ndarray.tobytes()
    
    def associate_websocket(self, client_id, websocket):
        """
        关联WebRTC连接和WebSocket连接
        
        参数:
        client_id: 客户端 ID
        websocket: 客户端的WebSocket连接
        """
        if client_id in self.webrtc_connections:
            conn = self.webrtc_connections[client_id]
            conn.websocket = websocket
            logger.warning(f"[SERVER-CONNECTION] 已关联WebSocket和WebRTC连接: {client_id}")
            return True
        return False
        
    async def process_audio_frame(self, frame, client_id):
        """
        处理WebRTC音频帧
        
        参数:
        frame: 音频帧
        client_id: 客户端 ID
        """
        try:
            # 初始化或获取计数器
            if client_id not in self.audio_packet_counters:
                self.audio_packet_counters[client_id] = 0
                self.audio_bytes_counters[client_id] = 0
                self.last_log_time[client_id] = 0
            
            # 增加帧计数
            self.audio_packet_counters[client_id] += 1
            counter = self.audio_packet_counters[client_id]
            
            # 添加明确的日志 - 记录开始处理音频
            logger.warning(f"[SERVER-AUDIO] 接收音频包 #{counter} 来自客户端 {client_id}, 时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
            
            # 1. 将音频帧转换为PCM格式 (原VAD链路需要的格式)
            audio_array = await self._convert_audio_to_pcm(frame)
            self.audio_bytes_counters[client_id] += len(audio_array)
            logger.warning(f"[SERVER-AUDIO] 音频转换完成，数据包 #{counter}，大小: {len(audio_array)} 字节，累计: {self.audio_bytes_counters[client_id]} 字节")
            
            # 2. 获取或创建持久化的WebRTC连接对象
            if client_id in self.webrtc_connections:
                conn = self.webrtc_connections[client_id]
                logger.warning(f"[SERVER-AUDIO] 使用已有WebRTC连接对象，客户端ID: {client_id}, ASR状态: {conn.asr_server_receive}")
            else:
                # 创建新的WebRTC连接对象并保存
                conn = WebRTCConnection(client_id)
                self.webrtc_connections[client_id] = conn
                logger.warning(f"[SERVER-AUDIO] 创建新的WebRTC连接对象，客户端ID: {client_id}")
            
            # 3. 将音频数据添加到缓冲区 - 直接添加到ASR音频列表而不是临时缓冲区
            # 这样可以确保收集到的音频段是连续的
            conn.asr_audio.append(audio_array)
            logger.warning(f"[SERVER-AUDIO] 音频数据已添加到ASR缓冲区，客户端: {client_id}, 包 #{counter}, 当前已收集 {len(conn.asr_audio)} 段音频")
            
            # 4. 音频包计数器
            packet_counter = self.audio_packet_counters[client_id]
            
            # 5. 当收集到足够多的音频段时（至少15段），设置VAD标志并触发ASR处理
            if len(conn.asr_audio) >= 15 and packet_counter % 30 == 0:
                logger.warning(f"[SERVER-AUDIO] 已收集足够的音频段: {len(conn.asr_audio)} > 15 段，准备触发ASR处理")
                # 设置VAD已检测到语音活动
                conn.client_have_voice = True
                # 标记语音片段结束，触发ASR处理
                conn.client_voice_stop = True
                logger.warning(f"[SERVER-AUDIO] 标记语音状态: have_voice=True, voice_stop=True，将触发ASR处理")
            
            # 6. 引入process_audio_internal函数
            try:
                from main.xiaozhi_server.core.handle.receiveAudioHandle import process_audio_internal
                logger.warning(f"[SERVER-AUDIO] 成功导入原有VAD处理链路 (主路径)")
            except ImportError:
                # 备选导入路径
                try:
                    from core.handle.receiveAudioHandle import process_audio_internal
                    logger.warning(f"[SERVER-AUDIO] 成功从备选路径导入原有VAD处理链路")
                except ImportError as e:
                    logger.error(f"[SERVER-AUDIO] 无法导入VAD处理链路: {str(e)}")
                    return
            
            # 7. 输出VAD状态
            logger.warning(f"[SERVER-AUDIO] VAD状态: have_voice={conn.client_have_voice}, voice_stop={conn.client_voice_stop}")
            
            # 8. 将音频数据传递到VAD处理链路
            result = None
            if conn.client_voice_stop and len(conn.asr_audio) >= 15:
                logger.warning(f"[SERVER-AUDIO] 开始处理整合的音频段，总共 {len(conn.asr_audio)} 段，准备调用ASR处理")
                # 直接在这里调用ASR处理，不使用VAD处理逻辑
                from core.handle.sendAudioHandle import send_stt_message
                from core.handle.intentHandler import handle_user_intent
                
                # 暂停接收新音频
                conn.asr_server_receive = False
                
                # 直接调用ASR接口处理累积的音频数据
                try:
                    text, extra_info = await conn.asr.speech_to_text(conn.asr_audio, conn.session_id)
                    logger.warning(f"[SERVER-AUDIO] ASR识别结果: '{text}'")
                except Exception as e:
                    logger.error(f"[SERVER-AUDIO-ERROR] ASR处理失败: {e}")
                    text = ""
                    extra_info = {}
                    
                # 清理ASR缓冲区，避免重复处理
                conn.asr_audio = []
                
                # 处理识别文本
                if text and len(text.strip()) > 0:
                    # 先检查WebSocket连接是否存在
                    if conn.websocket is None:
                        logger.warning(f"[SERVER-AUDIO] 检测到WebSocket连接不存在，无法发送ASR结果。仅记录结果：{text}")
                        
                        # 尝试使用备选方法通知客户端
                        try:
                            # 将ASR结果保存到服务器，让客户端主动查询
                            conn.last_asr_result = text
                            logger.warning(f"[SERVER-AUDIO] 已保存ASR结果到连接对象: {text}")
                        except Exception as e:
                            logger.error(f"[SERVER-AUDIO] 备用方法也失败: {e}")
                    else:
                        try:
                            # 处理用户意图
                            intent_handled = await handle_user_intent(conn, text)
                            if not intent_handled:
                                # 没有特殊意图，继续常规聊天
                                await send_stt_message(conn, text)
                                if hasattr(conn, 'use_function_call_mode') and conn.use_function_call_mode:
                                    # 使用function calling聊天
                                    conn.executor.submit(conn.chat_with_function_calling, text)
                                else:
                                    # 使用普通聊天
                                    conn.executor.submit(conn.chat, text)
                        except Exception as e:
                            logger.error(f"[SERVER-AUDIO-ERROR] 处理ASR结果时发生错误: {e}")
                            logger.error(f"[SERVER-AUDIO-ERROR] 堆栈跟踪: {traceback.format_exc()}")
                            # 尝试重置连接状态
                            conn.asr_server_receive = True
                
                # 清空音频缓冲区，准备下一轮收集
                conn.asr_audio.clear()
                # 重置VAD状态
                conn.reset_vad_states()
                # 恢复接收新音频
                conn.asr_server_receive = True
                logger.warning(f"[SERVER-AUDIO] ASR处理完成，已重置状态，恢复接收音频")
            else:
                # 正常的VAD处理
                logger.warning(f"[SERVER-AUDIO] 正常VAD处理，数据包 #{packet_counter}，音频长度: {len(audio_array)} 字节")
                result = await process_audio_internal(conn, audio_array)
                logger.warning(f"[SERVER-AUDIO] VAD处理链路已完成，数据包 #{packet_counter}，结果: {result}")
            
            # 9. 更新统计信息
            client_info = self.client_stats.get(client_id, {'frames_processed': 0, 'bytes_processed': 0})
            client_info['frames_processed'] = client_info.get('frames_processed', 0) + 1
            client_info['bytes_processed'] = client_info.get('bytes_processed', 0) + len(audio_array)
            self.client_stats[client_id] = client_info
            
            # 10. 定期输出统计信息
            if client_info['frames_processed'] % 100 == 0:
                logger.info(f"WebRTC已处理 {client_info['frames_processed']} 帧音频 [客户端: {client_id}]")
            
            return result
        
        except Exception as e:
            logger.error(f"[SERVER-AUDIO-ERROR] 处理音频帧时出错: {str(e)}")
            logger.error(f"[SERVER-AUDIO-ERROR] 错误详情: {e.__class__.__name__}: {str(e)}")
            import traceback
            logger.error(f"[SERVER-AUDIO-ERROR] 堆栈跟踪: {traceback.format_exc()}")
            return None
    
    async def handle_connection_failure(self, client_id):
        """
        处理连接失败
        
        Args:
            client_id: 客户端ID
        """
        logger.warning(f"WebRTC连接失败 [客户端: {client_id}]")
        # 这里可以实现重连逻辑，或者通知客户端切换到备用通信方式
    
    # 简化设计，移除了注册连接的方法
        
    async def close_connection(self, client_id):
        """
        关闭并清理WebRTC连接
        
        Args:
            client_id: 客户端 ID
        """
        # 关闭PeerConnection
        pc = self.peer_connections.get(client_id)
        if pc:
            await pc.close()
            self.peer_connections.pop(client_id, None)
            
        # 清理关联的资源
        self.audio_processors.pop(client_id, None)
        
        # 清理持久化的WebRTC连接对象
        self.webrtc_connections.pop(client_id, None)
        
        # 清理数据通道
        channels_to_remove = [k for k in self.data_channels if k.startswith(f"{client_id}_")]
        for channel_key in channels_to_remove:
            self.data_channels.pop(channel_key, None)
            
        logger.info(f"已关闭客户端 {client_id} 的连接")
    
    async def close_all_connections(self):
        """关闭所有连接"""
        logger.info("关闭所有WebRTC连接...")
        
        for client_id in list(self.peer_connections.keys()):
            await self.close_connection(client_id)
