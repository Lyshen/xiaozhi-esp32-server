import time
import numpy as np
import torch
import opuslib_next
from config.logger import setup_logging
from core.providers.vad.base import VADProviderBase

TAG = __name__
logger = setup_logging()


class VADProvider(VADProviderBase):
    def __init__(self, config):
        logger.bind(tag=TAG).info("SileroVAD", config)
        self.model, self.utils = torch.hub.load(
            repo_or_dir=config["model_dir"],
            source="local",
            model="silero_vad",
            force_reload=False,
        )
        (get_speech_timestamps, _, _, _, _) = self.utils

        self.decoder = opuslib_next.Decoder(16000, 1)
        self.vad_threshold = float(config.get("threshold", 0.5))
        self.silence_threshold_ms = int(config.get("min_silence_duration_ms", 1000))

    def is_vad(self, conn, audio_data):
        try:
            # 检查是否为PCM格式还是Opus格式
            # PCM数据通常以int16格式存储，尝试直接解析
            try:
                # 尝试将数据解析为PCM格式
                _ = np.frombuffer(audio_data, dtype=np.int16)
                # 如果可以解析为int16数组，则认为是PCM数据
                pcm_frame = audio_data
                logger.info(f"[VAD-DEBUG] 检测到PCM数据，长度: {len(pcm_frame)}字节")
            except Exception:
                # 如果不能解析为PCM，尝试作为Opus解码
                try:
                    logger.info(f"[VAD-DEBUG] 尝试作为Opus数据解码，长度: {len(audio_data)}字节")
                    pcm_frame = self.decoder.decode(audio_data, 960)
                    logger.info(f"[VAD-DEBUG] Opus解码成功，解码后长度: {len(pcm_frame)}字节")
                except Exception as e:
                    # 解码失败，记录错误并返回False
                    logger.info(f"解码错误: {e}")
                    return False
                
            # 将PCM数据添加到缓冲区
            conn.client_audio_buffer.extend(pcm_frame)  # 将新数据加入缓冲区

            # 处理缓冲区中的完整帧（每次处理512采样点）
            client_have_voice = False
            while len(conn.client_audio_buffer) >= 512 * 2:
                # 提取前512个采样点（1024字节）
                chunk = conn.client_audio_buffer[: 512 * 2]
                conn.client_audio_buffer = conn.client_audio_buffer[512 * 2 :]

                # 转换为模型需要的张量格式
                audio_int16 = np.frombuffer(chunk, dtype=np.int16)
                audio_float32 = audio_int16.astype(np.float32) / 32768.0
                audio_tensor = torch.from_numpy(audio_float32)

                # 检测语音活动
                with torch.no_grad():
                    speech_prob = self.model(audio_tensor, 16000).item()
                client_have_voice = speech_prob >= self.vad_threshold

                # 如果之前有声音，但本次没有声音，且与上次有声音的时间查已经超过了静默阈值，则认为已经说完一句话
                if conn.client_have_voice and not client_have_voice:
                    stop_duration = (
                        time.time() * 1000 - conn.client_have_voice_last_time
                    )
                    if stop_duration >= self.silence_threshold_ms:
                        conn.client_voice_stop = True
                if client_have_voice:
                    conn.client_have_voice = True
                    conn.client_have_voice_last_time = time.time() * 1000

            return client_have_voice
        except opuslib_next.OpusError as e:
            logger.bind(tag=TAG).info(f"解码错误: {e}")
        except Exception as e:
            logger.bind(tag=TAG).error(f"Error processing audio packet: {e}")

