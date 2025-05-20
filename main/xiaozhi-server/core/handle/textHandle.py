from config.logger import setup_logging
import json
from core.handle.abortHandle import handleAbortMessage
from core.handle.helloHandle import handleHelloMessage
from core.utils.util import remove_punctuation_and_length
from core.handle.receiveAudioHandle import startToChat, handleAudioMessage
from core.handle.sendAudioHandle import send_stt_message, send_tts_message
from core.handle.iotHandle import handleIotDescriptors, handleIotStatus
import asyncio

TAG = __name__
logger = setup_logging()


async def handleTextMessage(conn, message):
    """处理文本消息"""
    logger.bind(tag=TAG).info(f"收到文本消息：{message}")
    try:
        msg_json = json.loads(message)
        if isinstance(msg_json, int):
            await conn.websocket.send(message)
            return
        if msg_json["type"] == "hello":
            await handleHelloMessage(conn)
        elif msg_json["type"] == "abort":
            await handleAbortMessage(conn)
        elif msg_json["type"] == "listen":
            if "mode" in msg_json:
                conn.client_listen_mode = msg_json["mode"]
                logger.bind(tag=TAG).debug(f"客户端拾音模式：{conn.client_listen_mode}")
            if msg_json["state"] == "start":
                conn.client_have_voice = True
                conn.client_voice_stop = False
            elif msg_json["state"] == "stop":
                # 设置VAD状态标志
                conn.client_have_voice = True
                conn.client_voice_stop = True
                
                logger.bind(tag=TAG).warning(f"[按钮释放] 收到stop消息，设置 client_voice_stop = True")
                
                # 获取客户端ID
                device_id = conn.headers.get('device-id') if hasattr(conn, 'headers') else None
                logger.bind(tag=TAG).warning(f"[按钮释放] 客户端ID: {device_id}")
                
                # 1. 解决方案：使用全局变量
                try:
                    # 获取WebRTC模块
                    try:
                        import sys
                        # 从全局变量中获取WebRTC连接管理器
                        import builtins
                        rtc_manager = None
                        
                        # 尝试方法1：从sys.modules获取
                        if hasattr(sys.modules, 'main') and hasattr(sys.modules['main'], 'webrtc_module'):
                            logger.bind(tag=TAG).warning(f"[按钮释放] 从'main'获取webrtc_module")
                            rtc_manager = sys.modules['main'].webrtc_module.connection_manager
                            
                        # 尝试方法2：从builtins获取
                        if rtc_manager is None and hasattr(builtins, 'webrtc_manager'):
                            logger.bind(tag=TAG).warning(f"[按钮释放] 从builtins获取webrtc_manager")
                            rtc_manager = getattr(builtins, 'webrtc_manager')
                            
                        # 尝试方法3：和检查其他WebRTC相关模块
                        for module_name, module in list(sys.modules.items()):
                            # 检查该模块是否含有WebRTC相关的类
                            if 'webrtc' in module_name.lower():
                                logger.bind(tag=TAG).warning(f"[按钮释放] 检查模块: {module_name}")
                                # 检查模块中的属性和变量
                                for attr_name in dir(module):
                                    if 'manager' in attr_name.lower() or 'connect' in attr_name.lower():
                                        attr = getattr(module, attr_name)
                                        logger.bind(tag=TAG).warning(f"[按钮释放] 检查属性: {attr_name}, 类型: {type(attr)}")
                                        # 检查该属性是否是实例并有webrtc_connections属性
                                        if hasattr(attr, 'webrtc_connections'):
                                            rtc_manager = attr
                                            logger.bind(tag=TAG).warning(f"[按钮释放] 在{module_name}.{attr_name}中找到WebRTC连接管理器")
                                            break
                                if rtc_manager is not None:
                                    break
                        
                        if rtc_manager is not None:
                            logger.bind(tag=TAG).warning(f"[按钮释放] 成功获取WebRTC连接管理器，尝试获取连接: {device_id}")
                            # 找到该客户端的WebRTC连接并直接设置状态
                            if device_id in rtc_manager.webrtc_connections:
                                webrtc_conn = rtc_manager.webrtc_connections[device_id]
                                # 直接设置状态标志
                                webrtc_conn.client_voice_stop = True
                                webrtc_conn.client_voice_stop_requested = True
                                logger.bind(tag=TAG).warning(f"[按钮释放] 已直接设置WebRTC连接对象状态: voice_stop=True, stop_requested=True")
                            else:
                                logger.bind(tag=TAG).warning(f"[按钮释放] 找不到客户端{device_id}的WebRTC连接")
                    except Exception as e:
                        import traceback
                        logger.bind(tag=TAG).warning(f"[按钮释放] 获取WebRTC模块失败: {e}")
                        logger.bind(tag=TAG).warning(f"[按钮释放] 栈跟踪: {traceback.format_exc()}")
                        
                    # 2. 备用方案：设置全局标志
                    setattr(builtins, 'PUSH_TO_TALK_STOP_REQUESTED', True)
                    setattr(builtins, 'CLIENT_ID_FOR_STOP', device_id)
                    logger.bind(tag=TAG).warning(f"[按钮释放] 已设置全局标志 PUSH_TO_TALK_STOP_REQUESTED = True")
                except Exception as e:
                    logger.bind(tag=TAG).error(f"[按钮释放] 设置标志时出错: {e}")
                
                # 触发音频处理
                if len(conn.asr_audio) > 0:
                    logger.bind(tag=TAG).warning(f"[按钮释放] 将调用handleAudioMessage处理音频数据，数据量: {len(conn.asr_audio)} 段")
                    await handleAudioMessage(conn, b"")
                else:
                    logger.bind(tag=TAG).warning(f"[按钮释放] WebSocket对象不含音频数据，完全依赖WebRTC对象中的数据")
            elif msg_json["state"] == "detect":
                conn.asr_server_receive = False
                conn.client_have_voice = False
                conn.asr_audio.clear()
                if "text" in msg_json:
                    text = msg_json["text"]
                    _, text = remove_punctuation_and_length(text)

                    # 识别是否是唤醒词
                    is_wakeup_words = text in conn.config.get("wakeup_words")
                    # 是否开启唤醒词回复
                    enable_greeting = conn.config.get("enable_greeting", True)

                    if is_wakeup_words and not enable_greeting:
                        # 如果是唤醒词，且关闭了唤醒词回复，就不用回答
                        await send_stt_message(conn, text)
                        await send_tts_message(conn, "stop", None)
                    else:
                        # 否则需要LLM对文字内容进行答复
                        await startToChat(conn, text)
        elif msg_json["type"] == "iot":
            if "descriptors" in msg_json:
                asyncio.create_task(handleIotDescriptors(conn, msg_json["descriptors"]))
            if "states" in msg_json:
                asyncio.create_task(handleIotStatus(conn, msg_json["states"]))
    except json.JSONDecodeError:
        await conn.websocket.send(message)
