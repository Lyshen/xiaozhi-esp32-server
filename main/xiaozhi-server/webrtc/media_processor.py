#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
WebRTC媒体处理模块
负责音频和视频流的处理，替代原有Opus处理
"""

import logging
import asyncio
import av
import numpy as np
from aiortc.contrib.media import MediaStreamTrack, MediaStreamError

logger = logging.getLogger(__name__)

class MediaProcessor:
    """媒体处理器，处理音频流"""
    
    def __init__(self, app_context=None):
        """
        初始化媒体处理器
        
        Args:
            app_context: 应用程序上下文
        """
        self.app_context = app_context
        self.audio_processors = {}  # client_id -> AudioProcessor
        self.processing_enabled = True
        self.pending_audio_data = {}  # client_id -> [audio_data]
        logger.info("媒体处理器初始化完成")
    
    def create_audio_processor(self, client_id):
        """
        为客户端创建音频处理器
        
        Args:
            client_id: 客户端ID
            
        Returns:
            AudioProcessor: 创建的音频处理器
        """
        processor = AudioProcessor(client_id, self.app_context)
        self.audio_processors[client_id] = processor
        
        # 处理任何待处理的音频数据
        if client_id in self.pending_audio_data:
            for audio_data in self.pending_audio_data[client_id]:
                processor.process_audio_data(audio_data)
            del self.pending_audio_data[client_id]
            
        logger.info(f"已为客户端 {client_id} 创建音频处理器")
        return processor
    
    def get_audio_processor(self, client_id):
        """
        获取客户端的音频处理器，如不存在则创建
        
        Args:
            client_id: 客户端ID
            
        Returns:
            AudioProcessor: 客户端的音频处理器
        """
        if client_id not in self.audio_processors:
            return self.create_audio_processor(client_id)
        return self.audio_processors[client_id]
    
    async def process_audio(self, client_id, audio_data):
        """
        处理音频数据
        
        Args:
            client_id: 客户端ID
            audio_data: 音频数据
            
        Returns:
            bool: 处理是否成功
        """
        if not self.processing_enabled:
            logger.debug(f"音频处理已禁用，跳过 [客户端: {client_id}]")
            return False
        
        # 获取或创建音频处理器
        processor = self.get_audio_processor(client_id)
        
        try:
            # 异步处理音频数据
            asyncio.create_task(processor.process_audio_data(audio_data))
            return True
        except Exception as e:
            logger.exception(f"处理音频数据时出错 [客户端: {client_id}]: {e}")
            return False
    
    async def process_audio_frame(self, client_id, frame):
        """
        处理音频帧
        
        Args:
            client_id: 客户端ID
            frame: 音频帧
            
        Returns:
            bool: 处理是否成功
        """
        if not self.processing_enabled:
            return False
        
        processor = self.get_audio_processor(client_id)
        
        try:
            # 异步处理音频帧
            asyncio.create_task(processor.process_audio_frame(frame))
            return True
        except Exception as e:
            logger.exception(f"处理音频帧时出错 [客户端: {client_id}]: {e}")
            return False
    
    def remove_client(self, client_id):
        """
        移除客户端的处理器
        
        Args:
            client_id: 客户端ID
        """
        self.audio_processors.pop(client_id, None)
        self.pending_audio_data.pop(client_id, None)
        logger.info(f"已移除客户端 {client_id} 的音频处理器")


class AudioProcessor:
    """音频处理器，处理单个客户端的音频"""
    
    def __init__(self, client_id, app_context=None):
        """
        初始化音频处理器
        
        Args:
            client_id: 客户端ID
            app_context: 应用程序上下文
        """
        self.client_id = client_id
        self.app_context = app_context
        self.frame_queue = asyncio.Queue(maxsize=100)
        self.processing_task = None
        self.running = False
        
        # 音频参数
        self.sample_rate = 16000  # 采样率
        self.channels = 1  # 单声道
        self.frame_size = 960  # 每帧采样数 (60ms @ 16kHz)
        
        logger.info(f"音频处理器创建 [客户端: {client_id}]")
    
    async def start(self):
        """启动音频处理器"""
        if self.running:
            return
            
        self.running = True
        self.processing_task = asyncio.create_task(self._processing_loop())
        logger.info(f"音频处理器启动 [客户端: {self.client_id}]")
    
    async def stop(self):
        """停止音频处理器"""
        self.running = False
        if self.processing_task:
            try:
                self.processing_task.cancel()
                await asyncio.wait_for(self.processing_task, timeout=1.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            self.processing_task = None
        logger.info(f"音频处理器停止 [客户端: {self.client_id}]")
    
    async def process_audio_data(self, audio_data):
        """
        处理音频数据
        
        Args:
            audio_data: 音频数据
        """
        if not self.running:
            await self.start()
        
        try:
            # 将音频数据转换为帧
            # 这里假设音频数据是 PCM 16-bit
            samples = np.frombuffer(audio_data, dtype=np.int16)
            
            # 记录一下实际形状，用于调试
            logger.debug(f"接收到音频数据形状: {samples.shape}")
            
            try:
                # 创建 PyAV 音频帧
                # 尝试适应不同的输入形状
                if samples.size % self.channels == 0:
                    samples_reshaped = samples.reshape(-1, self.channels)
                    frame = av.AudioFrame.from_ndarray(
                        samples_reshaped,
                        format="s16",
                        layout="mono" if self.channels == 1 else "stereo"
                    )
                else:
                    # 如果无法整除通道数，可能需要截断或填充
                    logger.warning(f"音频数据大小 {samples.size} 不能被通道数 {self.channels} 整除")
                    # 截断到最近的可整除大小
                    trunc_size = (samples.size // self.channels) * self.channels
                    samples = samples[:trunc_size]
                    frame = av.AudioFrame.from_ndarray(
                        samples.reshape(-1, self.channels),
                        format="s16",
                        layout="mono" if self.channels == 1 else "stereo"
                    )
            except ValueError as e:
                # 如果仍然失败，尝试将4096作为通道数（客户端可能发送的形状）
                logger.warning(f"尝试特殊处理音频数据: {e}")
                # 检查是否可能是[4096, samples]形状的数据
                if samples.size % 4096 == 0:
                    # 将其转置为[samples, 4096]然后重新整形为[samples*4096//channels, channels]
                    reshaped = samples.reshape(-1, 4096).transpose().flatten()
                    if reshaped.size % self.channels == 0:
                        frame = av.AudioFrame.from_ndarray(
                            reshaped.reshape(-1, self.channels),
                            format="s16", 
                            layout="mono" if self.channels == 1 else "stereo"
                        )
                    else:
                        raise ValueError(f"无法将形状为{samples.shape}的数据重整为通道数{self.channels}")
                else:
                    raise
            frame.sample_rate = self.sample_rate
            
            # 将帧放入队列
            await self.frame_queue.put(frame)
            
        except Exception as e:
            logger.exception(f"处理音频数据时出错 [客户端: {self.client_id}]: {e}")
    
    async def process_audio_frame(self, frame):
        """
        处理音频帧
        
        Args:
            frame: 音频帧
        """
        if not self.running:
            await self.start()
            
        try:
            # 将帧放入队列
            await self.frame_queue.put(frame)
        except Exception as e:
            logger.exception(f"处理音频帧时出错 [客户端: {self.client_id}]: {e}")
    
    async def _processing_loop(self):
        """音频处理循环"""
        try:
            while self.running:
                # 从队列获取帧
                frame = await self.frame_queue.get()
                
                try:
                    # 在这里处理音频帧
                    # 可以调用原有的音频处理逻辑
                    await self._handle_audio_frame(frame)
                    
                except Exception as e:
                    logger.exception(f"处理音频帧时出错 [客户端: {self.client_id}]: {e}")
                finally:
                    # 标记任务完成
                    self.frame_queue.task_done()
        except asyncio.CancelledError:
            logger.info(f"音频处理循环已取消 [客户端: {self.client_id}]")
        except Exception as e:
            logger.exception(f"音频处理循环出错 [客户端: {self.client_id}]: {e}")
    
    async def _handle_audio_frame(self, frame):
        """
        处理单个音频帧的实际逻辑
        
        Args:
            frame: 音频帧
        """
        # 将此处替换为您原有的音频处理逻辑
        # 例如：语音识别、音频转写等
        
        # 如果app_context可用，可以调用原有功能
        if self.app_context and hasattr(self.app_context, 'audio_processor'):
            # 将 PyAV 帧转换为原系统期望的格式
            ndarray = frame.to_ndarray()
            bytes_data = ndarray.tobytes()
            
            # 假设原系统有这样的接口
            if hasattr(self.app_context.audio_processor, 'process_audio'):
                await self.app_context.audio_processor.process_audio(
                    self.client_id, 
                    bytes_data, 
                    sample_rate=frame.sample_rate
                )
