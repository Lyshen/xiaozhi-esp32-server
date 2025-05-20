#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
为connection_manager.py添加增强日志记录的修改部分
服务器管理员可以将此文件中的函数替换到connection_manager.py中对应位置
"""

# 修改 AudioTrackProcessor.recv 方法，增加音频帧接收日志
async def enhanced_recv(self):
    """
    接收音频帧，增加详细日志
    
    Returns:
        av.AudioFrame: 处理后的音频帧
    """
    frame = await self.track.recv()
    
    # 添加详细的帧接收日志
    import logging
    logger = logging.getLogger(__name__)
    logger.warning(f"[SERVER-AUDIO-RECV] 接收到音频帧: 格式={frame.format.name if frame.format else 'unknown'}, " +
                 f"采样率={frame.sample_rate}, 通道数={len(frame.planes)}, 样本数={frame.samples}")
    
    # 如果有回调函数，处理音频帧
    if self.on_frame:
        logger.warning(f"[SERVER-AUDIO-RECV] 开始处理音频帧: 大小={len(frame.planes[0].buffer) if frame.planes else 0} 字节")
        await self.on_frame(frame)
        logger.warning(f"[SERVER-AUDIO-RECV] 音频帧处理完成")
    
    # 返回处理后的帧
    return frame

# 创建音频处理器的回调函数，添加详细日志
async def enhanced_frame_callback(frame, client_id, connection_manager):
    """
    处理音频帧的回调函数，添加详细日志
    
    Args:
        frame: 音频帧
        client_id: 客户端ID
        connection_manager: 连接管理器实例，用于调用process_audio_frame方法
    """
    import logging
    logger = logging.getLogger(__name__)
    
    logger.warning(f"[SERVER-AUDIO-CALLBACK] 收到音频帧回调 [客户端: {client_id}]")
    logger.warning(f"[SERVER-AUDIO-CALLBACK] 音频帧详情: 格式={frame.format.name if frame.format else 'unknown'}, " +
                 f"采样率={frame.sample_rate}, 通道数={len(frame.planes)}, 样本数={frame.samples}")
    
    # 处理音频帧
    try:
        logger.warning(f"[SERVER-AUDIO-CALLBACK] 开始调用音频帧处理函数")
        await connection_manager.process_audio_frame(frame, client_id)
        logger.warning(f"[SERVER-AUDIO-CALLBACK] 音频帧处理完成")
    except Exception as e:
        logger.exception(f"[SERVER-AUDIO-ERROR] 处理音频帧时出错 [客户端: {client_id}]: {e}")

# 增强的 process_audio_frame 函数，添加详细日志
async def enhanced_process_audio_frame(self, frame, client_id):
    """
    处理WebRTC音频帧，添加详细日志
    
    参数:
    frame: 音频帧
    client_id: 客户端 ID
    """
    import sys
    import traceback
    import numpy as np
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        # 更新计数器
        if not hasattr(self, '_audio_packet_counters'):
            self._audio_packet_counters = {}
            self._audio_bytes_counters = {}
            self._last_log_time = {}
            
        if client_id not in self._audio_packet_counters:
            self._audio_packet_counters[client_id] = 0
            self._audio_bytes_counters[client_id] = 0
            self._last_log_time[client_id] = 0
            
        self._audio_packet_counters[client_id] += 1
        counter = self._audio_packet_counters[client_id]
        
        # 详细记录音频帧信息
        logger.warning(f"[SERVER-AUDIO-FRAME] 正在处理音频帧 #{counter} [客户端: {client_id}]")
        logger.warning(f"[SERVER-AUDIO-FRAME] 音频帧详情: 格式={frame.format.name if frame.format else 'unknown'}, " +
                     f"采样率={frame.sample_rate}, 通道数={len(frame.planes)}, 样本数={frame.samples}")
        
        # 1. 将PyAV音频帧转换为numpy数组
        logger.warning(f"[SERVER-AUDIO-FRAME] 开始将音频帧转换为numpy数组")
        try:
            audio_array = frame.to_ndarray().flatten()
            logger.warning(f"[SERVER-AUDIO-FRAME] 音频数据转换成功: 形状={audio_array.shape}, 类型={audio_array.dtype}")
        except Exception as conv_error:
            logger.error(f"[SERVER-AUDIO-ERROR] 转换音频帧时出错: {str(conv_error)}")
            audio_array_shape = "unknown"
            audio_array_dtype = "unknown"
            
            # 尝试备用方法转换
            logger.warning(f"[SERVER-AUDIO-FRAME] 尝试使用备用方法转换音频数据")
            buffer = bytes(frame.planes[0])
            audio_array = np.frombuffer(buffer, dtype=np.int16)
            logger.warning(f"[SERVER-AUDIO-FRAME] 备用方法转换成功: 形状={audio_array.shape}, 类型={audio_array.dtype}")
        
        # 2. 记录音频数据的统计信息
        self._audio_bytes_counters[client_id] += len(audio_array)
        logger.warning(f"[SERVER-AUDIO-FRAME] 音频数据统计: 当前帧大小={len(audio_array)}字节, " +
                     f"累计大小={self._audio_bytes_counters[client_id]}字节, 数据包数={counter}")
        
        # 定义内部连接类，用于传递到VAD/ASR
        class WebRTCConnection:
            def __init__(self, client_id):
                # 基本识别属性
                self.client_id = client_id
                self.headers = {"device-id": client_id}
                self.session_id = f"webrtc_{client_id}"
                
                # 为了兼容原有VAD处理，添加一些必要属性
                self.client_audio_buffer = bytearray()
                
                # VAD检测助手类，用于兼容现有的VAD接口
                class VADHelper:
                    def is_vad(self, conn, audio):
                        logger.warning(f"[SERVER-WEBRTC-VAD] VAD检测被调用 [客户端: {client_id}], 音频长度: {len(audio)} 字节")
                        return True, None
                
                self.vad = VADHelper()
                
                # ASR助手类
                class ASRHelper:
                    def speech_to_text(self, audio_data, **kwargs):
                        logger.warning(f"[SERVER-WEBRTC-ASR] ASR转写被调用 [客户端: {client_id}], 音频长度: {len(audio_data)} 字节")
                        return "WebRTC音频测试成功", None
                
                self.asr = ASRHelper()
                logger.warning(f"[SERVER-WEBRTC-CONN] 创建WebRTC连接对象完成 [客户端: {client_id}]")
        
        # 3. 创建连接对象
        logger.warning(f"[SERVER-AUDIO-FRAME] 创建WebRTC连接对象")
        conn = WebRTCConnection(client_id)
        
        # 4. 将音频数据添加到缓冲区
        logger.warning(f"[SERVER-AUDIO-FRAME] 将音频数据添加到缓冲区")
        conn.client_audio_buffer.extend(audio_array)
        logger.warning(f"[SERVER-AUDIO-BUFFER] 音频数据已添加到缓冲区 [客户端: {client_id}], " + 
                     f"数据包 #{counter}, 缓冲区大小: {len(conn.client_audio_buffer)} 字节")
        
        # 5. 导入VAD处理模块
        logger.warning(f"[SERVER-AUDIO-FRAME] 尝试导入VAD处理模块")
        process_audio_internal = None
        
        # 首先尝试主路径导入
        try:
            from main.xiaozhi_server.core.handle.receiveAudioHandle import process_audio_internal
            logger.warning(f"[SERVER-AUDIO-IMPORT] 成功从主路径导入VAD处理模块")
        except ImportError as main_import_error:
            logger.warning(f"[SERVER-AUDIO-IMPORT] 从主路径导入VAD处理模块失败: {str(main_import_error)}")
            
            # 尝试备选路径
            try:
                from core.handle.receiveAudioHandle import process_audio_internal
                logger.warning(f"[SERVER-AUDIO-IMPORT] 成功从备选路径导入VAD处理模块")
            except ImportError as alt_import_error:
                logger.error(f"[SERVER-AUDIO-ERROR] 无法导入VAD处理模块: {str(alt_import_error)}")
                logger.error(f"[SERVER-AUDIO-ERROR] Python路径: {sys.path}")
                return None
        
        # 如果模块导入失败，结束处理
        if process_audio_internal is None:
            logger.error(f"[SERVER-AUDIO-ERROR] VAD处理模块导入失败后未能恢复")
            return None
                    
            # 6. 调用VAD处理模块
            logger.warning(f"[SERVER-AUDIO-VAD] 开始调用VAD处理链路 [客户端: {client_id}], " +
                         f"数据包 #{counter}, 音频长度: {len(audio_array)} 字节")
                         
            # 记录音频数组的前20个值，帮助调试
            sample_data = audio_array[:20].tolist() if len(audio_array) > 20 else audio_array.tolist()
            logger.warning(f"[SERVER-AUDIO-VAD] 音频数据样本: {sample_data}")
            
            # 调用处理函数
            result = None
            try:
                result = await process_audio_internal(conn, audio_array)
            except Exception as vad_error:
                logger.error(f"[SERVER-AUDIO-ERROR] 调用VAD处理时出错: {str(vad_error)}")
                return None
            
            logger.warning(f"[SERVER-AUDIO-VAD] VAD处理链路调用完成 [客户端: {client_id}], " +
                         f"数据包 #{counter}, 结果: {result}")
            
            # 7. 更新统计信息
            client_info = self.client_stats.get(client_id, {'frames_processed': 0, 'bytes_processed': 0})
            client_info['frames_processed'] = client_info.get('frames_processed', 0) + 1
            client_info['bytes_processed'] = client_info.get('bytes_processed', 0) + len(audio_array)
            self.client_stats[client_id] = client_info
            
            # 输出统计信息
            logger.warning(f"[SERVER-AUDIO-STATS] 统计信息 [客户端: {client_id}]: " +
                         f"已处理 {client_info['frames_processed']} 帧音频, " +
                         f"共 {client_info['bytes_processed']} 字节")
            
            return result
        
    except Exception as e:
        logger.error(f"[SERVER-AUDIO-ERROR] 处理音频帧时出错: {str(e)}")
        logger.error(f"[SERVER-AUDIO-ERROR] 错误类型: {e.__class__.__name__}")
        logger.error(f"[SERVER-AUDIO-ERROR] 堆栈跟踪: {traceback.format_exc()}")
        return None
