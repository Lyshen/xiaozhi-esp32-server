#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
音频轨道处理模块
负责处理WebRTC音频轨道
"""

import asyncio
import logging
import traceback
from aiortc import MediaStreamTrack

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
        self._task = None
        
        # 立即启动背景任务以开始接收帧
        self._task = asyncio.create_task(self._receive_frames())
        
    async def _receive_frames(self):
        """持续接收并处理音频帧的背景任务"""
        try:
            logger.info(f"AudioTrackProcessor: 启动帧接收任务")
            while True:
                try:
                    frame = await self.track.recv()
                    await self._queue.put(frame)
                    
                    # 如果有回调函数，处理音频帧
                    if self.on_frame:
                        try:
                            logger.debug(f"AudioTrackProcessor: 调用帧回调函数")
                            await self.on_frame(frame)
                        except Exception as e:
                            logger.error(f"AudioTrackProcessor: 帧处理回调出错: {e}")
                            logger.error(f"堆栈跟踪: {traceback.format_exc()}")
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"AudioTrackProcessor: 接收帧时出错: {e}")
                    await asyncio.sleep(0.1)  # 避免CPU过载
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"AudioTrackProcessor: 帧接收任务错误: {e}")
            logger.error(f"堆栈跟踪: {traceback.format_exc()}")
    
    async def recv(self):
        """
        接收音频帧
        
        Returns:
            av.AudioFrame: 处理后的音频帧
        """
        if self._queue.empty():
            frame = await self.track.recv()
            # 确保帧回调被调用
            if self.on_frame:
                try:
                    await self.on_frame(frame)
                except Exception as e:
                    logger.error(f"AudioTrackProcessor: 直接帧处理回调出错: {e}")
        else:
            frame = await self._queue.get()
            
        # 返回处理后的帧
        return frame