import asyncio
from config.logger import setup_logging
import os
import numpy as np
import opuslib_next
from pydub import AudioSegment
from abc import ABC, abstractmethod
from core.utils.tts import MarkdownCleaner

TAG = __name__
logger = setup_logging()


class TTSProviderBase(ABC):
    def __init__(self, config, delete_audio_file):
        self.delete_audio_file = delete_audio_file
        self.output_file = config.get("output_dir")

    @abstractmethod
    def generate_filename(self):
        pass

    def to_tts(self, text):
        tmp_file = self.generate_filename()
        try:
            max_repeat_time = 5
            text = MarkdownCleaner.clean_markdown(text)
            while not os.path.exists(tmp_file) and max_repeat_time > 0:
                asyncio.run(self.text_to_speak(text, tmp_file))
                if not os.path.exists(tmp_file):
                    max_repeat_time = max_repeat_time - 1
                    logger.bind(tag=TAG).error(f"语音生成失败: {text}:{tmp_file}，再试{max_repeat_time}次")

            if max_repeat_time > 0:
                logger.bind(tag=TAG).info(f"语音生成成功: {text}:{tmp_file}，重试{5 - max_repeat_time}次")

            return tmp_file
        except Exception as e:
            logger.bind(tag=TAG).error(f"Failed to generate TTS file: {e}")
            return None

    @abstractmethod
    async def text_to_speak(self, text, output_file):
        pass

    def audio_to_opus_data(self, audio_file_path):
        """音频文件转换为Opus编码"""
        # 获取文件后缀名
        file_type = os.path.splitext(audio_file_path)[1]
        if file_type:
            file_type = file_type.lstrip('.')

        logger.debug(f"开始处理音频文件: {audio_file_path}")
            
        # 读取音频文件，-nostdin 参数：不要从标准输入读取数据，否则FFmpeg会阻塞
        audio = AudioSegment.from_file(audio_file_path, format=file_type, parameters=["-nostdin"])
        logger.debug(f"原始音频: 采样率={audio.frame_rate}Hz, 通道数={audio.channels}, 时长={len(audio)/1000.0}秒")

        # 保持与py-xiaozhi兼容的最基本参数: 16kHz采样率、单声道
        output_sample_rate = 16000
        audio = audio.set_channels(1).set_frame_rate(output_sample_rate).set_sample_width(2)

        # 音频时长(秒)
        duration = len(audio) / 1000.0

        # 获取原始PCM数据（16位小端）
        raw_data = audio.raw_data
        logger.debug(f"处理后音频: 采样率={output_sample_rate}Hz, 通道数=1, PCM数据长度={len(raw_data)}字节")

        # 初始化Opus编码器 - 使用和解码器相同的参数
        encoder = opuslib_next.Encoder(output_sample_rate, 1, opuslib_next.APPLICATION_AUDIO)

        # 使用小帧长来保证兼容性
        frame_duration = 20  # 20ms per frame
        frame_size = int(output_sample_rate * frame_duration / 1000)  # 320 samples/frame (20ms at 16kHz)
        logger.debug(f"编码参数: 帧长={frame_duration}ms, 每帧样本数={frame_size}, 每帧字节数={frame_size*2}")
        
        opus_datas = []
        max_buffer_size = 0
        
        # 使用可控的小分片处理PCM数据 - 避免生成过大的帧
        for i in range(0, len(raw_data), frame_size * 2):  # 16bit=2bytes/sample
            # 获取当前帧的二进制数据
            chunk = raw_data[i:i + frame_size * 2]

            # 如果最后一帧不足，补零
            if len(chunk) < frame_size * 2:
                padding_size = frame_size * 2 - len(chunk)
                chunk += b'\x00' * padding_size
                logger.debug(f"最后一帧数据不足，补充{padding_size}字节的零")

            # 转换为numpy数组处理
            np_frame = np.frombuffer(chunk, dtype=np.int16)

            # 编码Opus数据
            opus_data = encoder.encode(np_frame.tobytes(), frame_size)
            max_buffer_size = max(max_buffer_size, len(opus_data))
            opus_datas.append(opus_data)
        
        # 打印详细的调试信息
        logger.info(f"Opus编码完成: 帧数={len(opus_datas)}, 最大帧大小={max_buffer_size}字节, 采样率={output_sample_rate}Hz, 帧长={frame_duration}ms")
        
        return opus_datas, duration
