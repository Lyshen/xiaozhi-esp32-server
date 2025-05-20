/**
 * WebRTC功能使用示例
 */

import { CosplayClient } from './client';

/**
 * 创建一个使用WebRTC的客户端实例
 */
function createWebRTCClient() {
  // 创建客户端配置
  const config = {
    serverUrl: 'wss://xiaozhi.qiniu.io/ws',
    deviceId: 'demo-device',
    clientId: 'webrtc-client',
    
    // 音频配置
    audioConfig: {
      format: 'pcm' as const,
      sampleRate: 16000,
      channels: 1,
      frameDuration: 20,
      
      // WebRTC配置
      useWebRTC: true,
      webrtcSignalingUrl: 'wss://xiaozhi.qiniu.io/ws/signaling',
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true
    },
    
    // 重连配置
    reconnect: {
      enabled: true,
      maxAttempts: 10,
      delay: 1000
    }
  };
  
  // 创建客户端实例
  const client = new CosplayClient(config);
  
  // 设置事件监听器
  client.on('connected', () => {
    console.log('已连接到服务器');
    client.startListening().catch(err => console.error('录音失败', err));
  });
  
  client.on('disconnected', () => console.log('与服务器断开连接'));
  client.on('error', (error: Error) => console.error('发生错误:', error));
  client.on('speechRecognition', (text: string, isFinal: boolean) => {
    console.log(`语音识别结果 (${isFinal ? '最终' : '中间'})：${text}`);
  });
  
  // 连接到服务器
  client.connect().catch(err => console.error('连接服务器失败', err));
  
  return client;
}

// 创建并导出客户端实例
export const webrtcClient = createWebRTCClient();
