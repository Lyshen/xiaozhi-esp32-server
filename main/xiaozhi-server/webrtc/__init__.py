#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
WebRTC模块
提供WebRTC音频传输和信令功能
"""

import logging
from .config import WebRTCConfig
from .signaling import SignalingHandler
from .connection_manager import ConnectionManager
from .media_processor import MediaProcessor

logger = logging.getLogger(__name__)

class WebRTCModule:
    """WebRTC模块主类，负责初始化和管理WebRTC功能"""
    
    def __init__(self, app_context, config):
        """
        初始化WebRTC模块
        
        Args:
            app_context: 应用程序上下文
            config: 配置字典
        """
        self.app_context = app_context
        self.config = WebRTCConfig(config.get('webrtc', {}))
        self.enabled = self.config.enabled
        
        if not self.enabled:
            logger.info("WebRTC模块已禁用")
            return
        
        logger.info("初始化WebRTC模块...")
        
        # 创建媒体处理器
        self.media_processor = MediaProcessor(app_context)
        
        # 创建连接管理器
        self.connection_manager = ConnectionManager(self.config)
        
        # 创建信令处理器
        self.signaling_handler = SignalingHandler(self.connection_manager)
        
        logger.info("WebRTC模块初始化完成")
    
    async def setup_routes(self, app):
        """
        设置WebRTC信令相关路由
        
        Args:
            app: aiohttp应用程序实例
        """
        if not self.enabled:
            logger.info("WebRTC已禁用，跳过路由设置")
            return
            
        signaling_path = self.config.signaling_path
        app.router.add_get(signaling_path, self.handle_signaling_websocket)
        logger.info(f"WebRTC信令WebSocket路由已添加: {signaling_path}")
    
    async def handle_signaling_websocket(self, request):
        """
        处理信令WebSocket连接
        
        Args:
            request: HTTP请求对象
            
        Returns:
            WebSocketResponse: WebSocket响应对象
        """
        return await self.signaling_handler.handle_websocket(request)
    
    async def process_audio(self, client_id, audio_data):
        """
        处理音频数据
        
        Args:
            client_id: 客户端ID
            audio_data: 音频数据
            
        Returns:
            bool: 处理是否成功
        """
        if not self.enabled:
            return False
            
        return await self.media_processor.process_audio(client_id, audio_data)
    
    def is_webrtc_enabled(self):
        """
        检查WebRTC功能是否启用
        
        Returns:
            bool: 是否启用WebRTC
        """
        return self.enabled
        
    def should_replace_opus(self):
        """
        检查是否应该用WebRTC替换Opus
        
        Returns:
            bool: 是否替换Opus
        """
        return self.enabled and self.config.replace_opus
        
    async def shutdown(self):
        """关闭WebRTC模块"""
        if not self.enabled:
            return
            
        logger.info("关闭WebRTC模块...")
        
        # 关闭所有连接
        await self.connection_manager.close_all_connections()
        
        logger.info("WebRTC模块已关闭")
