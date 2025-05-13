import os
import uuid
import json
import base64
import io
import requests
import numpy as np
import opuslib_next
from datetime import datetime
from pydub import AudioSegment
from core.utils.util import check_model_key
from core.providers.tts.base import TTSProviderBase
from config.logger import setup_logging

TAG = __name__
logger = setup_logging()


class TTSProvider(TTSProviderBase):
    def __init__(self, config, delete_audio_file):
        super().__init__(config, delete_audio_file)
        self.appid = config.get("appid")
        self.access_token = config.get("access_token")
        self.cluster = config.get("cluster")

        if config.get("private_voice"):
            self.voice = config.get("private_voice")
        else:
            self.voice = config.get("voice")

        self.api_url = config.get("api_url")
        self.authorization = config.get("authorization")
        self.header = {"Authorization": f"{self.authorization}{self.access_token}"}
        check_model_key("TTS", self.access_token)

    def generate_filename(self, extension=".wav"):
        return os.path.join(
            self.output_file,
            f"tts-{datetime.now().date()}@{uuid.uuid4().hex}{extension}",
        )

    async def text_to_speak(self, text, output_file):
        request_json = {
            "app": {
                "appid": f"{self.appid}",
                "token": "access_token",
                "cluster": self.cluster,
            },
            "user": {"uid": "1"},
            "audio": {
                "voice_type": self.voice,
                "encoding": "wav",      # 火山引擎支持的格式
                "speed_ratio": 1.0,
                "volume_ratio": 1.0,
                "pitch_ratio": 1.0,
            },
            "request": {
                "reqid": str(uuid.uuid4()),
                "text": text,
                "text_type": "plain",
                "operation": "query",
                "with_frontend": 1,
                "frontend_type": "unitTson",
            },
        }

        try:
            # 记录开始时间，用于性能分析
            start_time = datetime.now()
            
            # 发送API请求
            resp = requests.post(
                self.api_url, json.dumps(request_json), headers=self.header
            )
            
            # 检查响应
            if "data" not in resp.json():
                raise Exception(
                    f"{__name__} status_code: {resp.status_code} response: {resp.content}"
                )
                
            # 解码Base64音频数据
            api_time = datetime.now()
            logger.bind(tag=TAG).debug(f"火山引擎API响应时间: {(api_time - start_time).total_seconds():.3f}秒")
            
            audio_data = base64.b64decode(resp.json()["data"])
            
            # 仅为兼容性保存文件 (可以考虑在生产环境移除此部分)
            with open(output_file, "wb") as f:
                f.write(audio_data)

            # 直接在内存中处理音频数据 - 跳过文件I/O操作
            audio_io = io.BytesIO(audio_data)
            audio = AudioSegment.from_file(audio_io, format="wav")
            
            # 执行必要的音频转换
            output_sample_rate = 16000
            audio = audio.set_channels(1).set_frame_rate(output_sample_rate).set_sample_width(2)
            
            # 获取音频时长
            duration = len(audio) / 1000.0
            
            # 直接获取PCM数据
            raw_data = audio.raw_data
            
            # 获取音频转换时间
            conversion_time = datetime.now()
            logger.bind(tag=TAG).debug(f"音频转换时间: {(conversion_time - api_time).total_seconds():.3f}秒")
            
            # Opus编码参数
            frame_duration = 20  # 20ms per frame
            frame_size = int(output_sample_rate * frame_duration / 1000)  # 320 samples/frame (20ms at 16kHz)
            
            # 初始化Opus编码器
            encoder = opuslib_next.Encoder(output_sample_rate, 1, opuslib_next.APPLICATION_AUDIO)
            
            # 直接编码为Opus格式
            opus_datas = []
            max_buffer_size = 0
            
            for i in range(0, len(raw_data), frame_size * 2):
                chunk = raw_data[i:i + frame_size * 2]
                
                # 处理最后一帧不足的情况
                if len(chunk) < frame_size * 2:
                    padding_size = frame_size * 2 - len(chunk)
                    chunk += b'\x00' * padding_size
                
                # 编码为Opus
                np_frame = np.frombuffer(chunk, dtype=np.int16)
                opus_data = encoder.encode(np_frame.tobytes(), frame_size)
                max_buffer_size = max(max_buffer_size, len(opus_data))
                opus_datas.append(opus_data)
            
            # 完成编码的时间
            encoding_time = datetime.now()
            logger.bind(tag=TAG).debug(f"Opus编码时间: {(encoding_time - conversion_time).total_seconds():.3f}秒")
            
            # 记录总处理时间
            total_time = (encoding_time - start_time).total_seconds()
            logger.bind(tag=TAG).info(f"优化后TTS处理总时间: {total_time:.3f}秒, 帧数: {len(opus_datas)}, 音频长度: {duration:.2f}秒")
            
            # 创建一个临时的opus_datas属性，以便base.py中的to_tts方法能够正确处理
            setattr(self, '_opus_datas', opus_datas)
            setattr(self, '_audio_duration', duration)
            
            return opus_datas, duration
            
        except Exception as e:
            logger.bind(tag=TAG).error(f"火山引擎TTS处理失败: {e}")
            raise Exception(f"{__name__} error: {e}")
