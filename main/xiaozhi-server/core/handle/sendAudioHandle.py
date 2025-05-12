from config.logger import setup_logging
import json
import asyncio
import time
from core.utils.util import (
    get_string_no_punctuation_or_emoji,
)

TAG = __name__
logger = setup_logging()


async def sendAudioMessage(conn, audios, text, text_index=0):
    # 发送句子开始消息
    if text_index == conn.tts_first_text_index:
        logger.bind(tag=TAG).info(f"发送第一段语音: {text}")
    await send_tts_message(conn, "sentence_start", text)

    # 播放音频
    await sendAudio(conn, audios)

    await send_tts_message(conn, "sentence_end", text)

    # 发送结束消息（如果是最后一个文本）
    if conn.llm_finish_task and text_index == conn.tts_last_text_index:
        await send_tts_message(conn, "stop", None)
        if conn.close_after_chat:
            await conn.close()


# 播放音频
async def sendAudio(conn, audios):
    # 流控参数优化 - 使用与音频编码器相同的帧时长
    frame_duration = 20  # 帧时长改为20ms，与Opus编码设置匹配
    
    # 记录发送开始时间
    start_time = time.perf_counter()
    play_position = 0
    total_frames = len(audios)
    
    logger.bind(tag=TAG).debug(f"开始发送音频: {total_frames}帧, 帧长={frame_duration}ms")

    # 预缓冲：发送前几帧以减少初始延迟
    pre_buffer = min(5, len(audios))  # 增加预缓冲数量
    for i in range(pre_buffer):
        await conn.websocket.send(audios[i])
        play_position += frame_duration

    # 正常播放剩余帧
    for i, opus_packet in enumerate(audios[pre_buffer:]):
        if conn.client_abort:
            logger.bind(tag=TAG).debug("播放中断")
            return

        # 计算预期发送时间
        expected_time = start_time + (play_position / 1000)
        current_time = time.perf_counter()
        delay = expected_time - current_time
        
        # 限制最大延迟，避免延迟过大
        if delay > 0.1:  # 最大延迟100ms
            delay = 0.1
            
        if delay > 0:
            await asyncio.sleep(delay)

        await conn.websocket.send(opus_packet)
        play_position += frame_duration
        
        # 每50帧打印一次进度
        if (i + pre_buffer) % 50 == 0:
            progress = (i + pre_buffer) / total_frames * 100
            logger.bind(tag=TAG).debug(f"播放进度: {progress:.1f}%, 帧:{i + pre_buffer}/{total_frames}")
    
    # 计算实际播放持续时间
    actual_duration = time.perf_counter() - start_time
    expected_duration = (total_frames * frame_duration) / 1000
    logger.bind(tag=TAG).debug(f"音频播放完成: 实际时长={actual_duration:.2f}秒, 预期时长={expected_duration:.2f}秒")


async def send_tts_message(conn, state, text=None):
    """发送 TTS 状态消息"""
    message = {"type": "tts", "state": state, "session_id": conn.session_id}
    if text is not None:
        message["text"] = text

    # TTS播放结束
    if state == "stop":
        # 播放提示音
        tts_notify = conn.config.get("enable_stop_tts_notify", False)
        if tts_notify:
            stop_tts_notify_voice = conn.config.get(
                "stop_tts_notify_voice", "config/assets/tts_notify.mp3"
            )
            audios, duration = conn.tts.audio_to_opus_data(stop_tts_notify_voice)
            await sendAudio(conn, audios)
        # 清除服务端讲话状态
        conn.clearSpeakStatus()

    # 发送消息到客户端
    await conn.websocket.send(json.dumps(message))


async def send_stt_message(conn, text):
    """发送 STT 状态消息"""
    stt_text = get_string_no_punctuation_or_emoji(text)
    await conn.websocket.send(
        json.dumps({"type": "stt", "text": stt_text, "session_id": conn.session_id})
    )
    await conn.websocket.send(
        json.dumps(
            {
                "type": "llm",
                "text": "😊",
                "emotion": "happy",
                "session_id": conn.session_id,
            }
        )
    )
    await send_tts_message(conn, "start")
