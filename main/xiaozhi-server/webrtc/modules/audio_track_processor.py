#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
音频轨道处理模块
负责处理WebRTC音频轨道
"""

import asyncio
import logging
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