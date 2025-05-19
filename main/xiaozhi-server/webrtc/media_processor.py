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
        
        # 统计信息
        self.audio_packets = 0  # 音频数据包计数
        self.audio_bytes = 0    # 音频数据字节计数
        
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
            # WebRTC解码后的音频数据处理
            # WebRTC默认使用Opus编码，解码后是PCM 16-bit
            samples = np.frombuffer(audio_data, dtype=np.int16)
            
            # 检查音频数据大小是否是预期帧大小的倍数 - 支持两种常见的帧大小
            frame_size_20ms = 320  # 20毫秒@16kHz=320个样本
            frame_size_64ms = 1024  # 64毫秒@16kHz=1024个样本 (WebRTC常用)
            
            if samples.size % frame_size_20ms == 0:
                frame_size = frame_size_20ms
                logger.debug(f"使用帧大小: {frame_size_20ms} (20ms)")
            elif samples.size % frame_size_64ms == 0:
                frame_size = frame_size_64ms
                logger.debug(f"使用帧大小: {frame_size_64ms} (64ms)")
            else:
                frame_size = frame_size_20ms  # 默认使用320
                logger.warning(f"音频数据大小 {samples.size} 不是标准帧大小的倍数，使用默认值: {frame_size}")
            
            # 截断到最近的帧边界
            samples = samples[:samples.size // frame_size * frame_size]
            
            # 将数据分割成多个帧
            frames = np.split(samples, samples.size // frame_size)
            
            # 处理每一帧
            for frame_samples in frames:
                # 创建PyAV音频帧
                # 形状调整为[1, samples]而非[-1, channels]
                frame = av.AudioFrame.from_ndarray(
                    frame_samples.reshape(1, -1),
                    format="s16",
                    layout="mono" if self.channels == 1 else "stereo"
                )
                frame.sample_rate = self.sample_rate
                
                # 将帧放入队列
                await self.frame_queue.put(frame)
                
                # 记录统计信息
                self.audio_packets += 1
                self.audio_bytes += len(audio_data)
                
        except Exception as e:
            logger.error(f"处理音频数据时出错: {str(e)}")
            raise
            
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
        try:
            # 输出谁试信息 - 正确访问AV音频格式属性
            # PyAV中是通过layout访问通道信息
            logger.warning(f"[XIAOZHI-SERVER] 处理音频帧, 客户端ID: {self.client_id}, 帧采样率: {frame.sample_rate}, 格式: {frame.format.name}, 通道布局: {frame.layout.name}")
            
            # 尝试获取WebRTC连接管理器
            connection_manager = None
            
            # 方式1: 直接从 app_context 获取
            if self.app_context and hasattr(self.app_context, 'webrtc_manager'):
                connection_manager = self.app_context.webrtc_manager
                logger.info(f"[XIAOZHI-SERVER] 从 app_context.webrtc_manager 获取到WebRTC连接管理器")
            
            # 方式2: 通过 webrtc_module 获取
            elif self.app_context and hasattr(self.app_context, 'webrtc_module'):
                webrtc_module = self.app_context.webrtc_module
                # 检查是否直接有connection_manager属性
                if hasattr(webrtc_module, 'connection_manager'):
                    connection_manager = webrtc_module.connection_manager
                    logger.info(f"[XIAOZHI-SERVER] 从 webrtc_module.connection_manager 获取到WebRTC连接管理器")
                # 检查是否有get_connection_manager方法
                elif hasattr(webrtc_module, 'get_connection_manager'):
                    connection_manager = webrtc_module.get_connection_manager()
                    logger.info(f"[XIAOZHI-SERVER] 通过 webrtc_module.get_connection_manager() 获取到WebRTC连接管理器")
            
            # 方式3: 尝试从全局模块导入
            if not connection_manager:
                try:
                    import sys
                    try:
                        from main.xiaozhi_server.webrtc.connection_manager import ConnectionManager
                        logger.warning(f"[XIAOZHI-SERVER] 尝试从主模块导入ConnectionManager")
                        # 对于已存在的全局实例，可以查找 sys.modules
                        for module_name, module in sys.modules.items():
                            if hasattr(module, 'connection_manager') and isinstance(module.connection_manager, ConnectionManager):
                                connection_manager = module.connection_manager
                                logger.warning(f"[XIAOZHI-SERVER] 从模块 {module_name} 找到全局ConnectionManager实例")
                                break
                    except ImportError:
                        from webrtc.connection_manager import ConnectionManager
                        logger.warning(f"[XIAOZHI-SERVER] 尝试从相对路径导入ConnectionManager")
                        for module_name, module in sys.modules.items():
                            if hasattr(module, 'connection_manager') and isinstance(module.connection_manager, ConnectionManager):
                                connection_manager = module.connection_manager
                                logger.warning(f"[XIAOZHI-SERVER] 从模块 {module_name} 找到全局ConnectionManager实例")
                                break
                except Exception as e:
                    logger.warning(f"[XIAOZHI-SERVER] 无法导入ConnectionManager: {str(e)}")
            
            # 如果找到连接管理器，则调用process_audio_frame方法
            if connection_manager:
                logger.warning(f"[XIAOZHI-SERVER] 成功获取到WebRTC连接管理器，传递音频帧")
                await connection_manager.process_audio_frame(frame, self.client_id)
            else:
                # 如果没有WebRTC管理器，尝试使用原有音频处理
                logger.warning(f"[XIAOZHI-SERVER] WebRTC管理器不可用，尝试使用原有音频处理逻辑")
                
                # 转换PyAV音频帧为字节数据
                frame_bytes = frame.to_ndarray().tobytes()
                
                # 直接使用我们自己的处理方法来处理音频帧
                logger.warning(f"[XIAOZHI-SERVER] 使用内部音频处理逻辑")
                await self.process_audio_data(frame_bytes)
                
                # 如果app_context有单独的audio_processor，也可以尝试调用
                if self.app_context and hasattr(self.app_context, 'audio_processor') and \
                   hasattr(self.app_context.audio_processor, 'process_audio'):
                    logger.warning(f"[XIAOZHI-SERVER] 同时调用app_context的音频处理逻辑")
                    try:
                        await self.app_context.audio_processor.process_audio(
                            self.client_id,
                            frame_bytes,  # 使用已定义的frame_bytes变量
                            sample_rate=frame.sample_rate
                        )
                    except Exception as e:
                        logger.error(f"[XIAOZHI-SERVER] 调用app_context音频处理器失败: {str(e)}")
                        # 继续执行，因为我们已经使用内部处理方法处理了音频
        except Exception as e:
            logger.error(f"[XIAOZHI-SERVER-ERROR] 处理音频帧时出错: {str(e)}")
            import traceback
            logger.error(f"[XIAOZHI-SERVER-ERROR] 堆栈跟踪: {traceback.format_exc()}")
