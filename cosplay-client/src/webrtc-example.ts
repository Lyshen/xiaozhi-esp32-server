/**
 * 这是一个使用WebRTC功能的示例文件
 * 展示如何配置和使用WebRTC音频连接
 */

import { CosplayClient } from './client';

/**
 * 创建一个使用WebRTC的客户端实例
 */
function createWebRTCClient() {
  // 创建客户端配置
  const config = {
    serverUrl: 'wss://xiaozhi.qiniu.io/ws', // 服务器WebSocket地址
    deviceId: 'demo-device-001',            // 设备标识
    clientId: 'webrtc-client',              // 客户端标识
    
    // 包含WebRTC配置的音频配置
    audioConfig: {
      format: 'pcm' as const,               // 使用PCM格式
      sampleRate: 16000,                    // 16kHz采样率
      channels: 1,                          // 单声道
      frameDuration: 20,                    // 20ms帧长度
      
      // WebRTC相关配置
      useWebRTC: true,                      // 启用WebRTC
      webrtcSignalingUrl: 'wss://xiaozhi.qiniu.io/ws/signaling', // 信令服务器地址
      echoCancellation: true,               // 启用回声消除
      noiseSuppression: true,               // 启用噪声抑制
      autoGainControl: true                 // 启用自动增益控制
    },
    
    // 自动重连配置
    reconnect: {
      enabled: true,
      maxAttempts: 10,
      delay: 1000,
      maxDelay: 30000,
      factor: 1.5
    }
  };
  
  // 创建客户端实例
  const client = new CosplayClient(config);
  
  // 设置事件监听器
  client.on('connected', () => {
    console.log('已连接到服务器');
    
    // 连接成功后开始录音
    client.startListening().then(success => {
      if (success) {
        console.log('录音开始');
      } else {
        console.error('录音失败');
      }
    });
  });
  
  client.on('disconnected', () => {
    console.log('与服务器断开连接');
  });
  
  client.on('error', (error: Error) => {
    console.error('发生错误:', error);
  });
  
  client.on('speechRecognition', (text: string, isFinal: boolean) => {
    console.log(`语音识别结果 (${isFinal ? '最终' : '中间'})：${text}`);
  });
  
  // 连接到服务器
  client.connect().then(success => {
    if (success) {
      console.log('成功连接到服务器');
    } else {
      console.error('连接服务器失败');
    }
  });
  
  return client;
}

// 使用WebRTC客户端的示例
const webrtcClient = createWebRTCClient();

// 导出客户端实例以便外部使用
export { webrtcClient };
