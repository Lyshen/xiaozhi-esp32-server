#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
WebRTC配置模块
负责解析和管理WebRTC相关配置
"""

class WebRTCConfig:
    """WebRTC配置类，处理WebRTC相关设置"""
    
    def __init__(self, config_dict):
        """
        初始化WebRTC配置
        
        Args:
            config_dict: 包含WebRTC配置的字典
        """
        self.enabled = config_dict.get('enabled', False)
        self.signaling_path = config_dict.get('signaling_path', '/ws/signaling')
        self.stun_servers = config_dict.get('stun_servers', [
            {"urls": "stun:stun.chat.bilibili.com:3478"},
            {"urls": "stun:stun.miwifi.com:3478"}
        ])
        self.turn_servers = config_dict.get('turn_servers', [])
        self.replace_opus = config_dict.get('replace_opus', True)
        
        # 其他WebRTC配置参数
        self.max_retries = config_dict.get('max_retries', 3)
        self.retry_interval = config_dict.get('retry_interval', 1)  # 秒
        self.connection_timeout = config_dict.get('connection_timeout', 30)  # 秒
        
    def to_dict(self):
        """
        将配置转换为字典形式
        
        Returns:
            dict: 包含配置信息的字典
        """
        return {
            "enabled": self.enabled,
            "signaling_path": self.signaling_path,
            "stun_servers": self.stun_servers,
            "turn_servers": self.turn_servers,
            "replace_opus": self.replace_opus,
            "max_retries": self.max_retries,
            "retry_interval": self.retry_interval,
            "connection_timeout": self.connection_timeout
        }
        
    def get_ice_servers(self):
        """
        获取ICE服务器列表(合并STUN和TURN)
        
        Returns:
            list: ICE服务器列表
        """
        return self.stun_servers + self.turn_servers
