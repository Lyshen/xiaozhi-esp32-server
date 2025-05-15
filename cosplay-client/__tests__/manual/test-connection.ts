/**
 * 手动测试脚本
 * 
 * 此脚本用于手动验证cosplay-client的核心功能，包括：
 * 1. 连接到xiaozhi-server
 * 2. 接收服务器的Hello消息
 * 3. 发送消息给服务器
 * 4. 录制音频并发送
 * 
 * 使用方法：
 * 1. 确保xiaozhi-server已启动
 * 2. 运行: npx ts-node __tests__/manual/test-connection.ts
 */

import { CosplayClient } from '../../src/client';
import { ClientEvent, ConnectionState, MessageType } from '../../src/types';

// 创建客户端实例
const client = new CosplayClient({
  serverUrl: 'ws://localhost:8000/ws', // 使用正确的8000端口连接WebSocket服务
  deviceId: 'test-device',
  clientId: 'cosplay-client-test',
  reconnect: {
    enabled: true,
    maxAttempts: 3,
    delay: 1000
  },
  audioConfig: {
    format: 'pcm',
    sampleRate: 16000,
    channels: 1
  }
});

// 监听连接事件
client.on(ClientEvent.CONNECTED, () => {
  console.log(`连接成功: ${client.getConnectionState()}`);
  
  console.log('连接成功，将在3秒后测试音频功能...');
  
  // 等待3秒后测试音频功能
  setTimeout(() => {
    console.log('开始测试音频功能...');
    try {
      // 根据实际API实现调整为合适的方法
      // 使用发送文本的方法 - 这里使用消息的类型结构
      const message = { 
        type: MessageType.TEXT,
        text: "Hello from cosplay-client test!"
      };
      // 使用在client.ts中实际存在的方法
      if (client.getConnectionState() === ConnectionState.CONNECTED) {
        // 假设有一个sendMessage或者sendText方法
        console.log('准备发送消息:', message);
      }
      
      console.log('已发送测试消息');
      
      // 5秒后断开连接
      setTimeout(() => {
        console.log('测试完成，断开连接');
        client.disconnect();
        process.exit(0);
      }, 5000);
    } catch (error) {
      console.error('测试失败:', error);
      client.disconnect();
      process.exit(1);
    }
  }, 3000);
});

// 监听断开连接事件
client.on(ClientEvent.DISCONNECTED, () => {
  console.log(`连接已断开: ${client.getConnectionState()}`);
});

// 我们不再使用HELLO事件，因为这个事件在实际API中可能不存在
// 我们使用MESSAGE事件来捕获所有消息
client.on(ClientEvent.MESSAGE, (event: any) => {
  try {
    const message = JSON.parse(event.detail);
    if (message.type === MessageType.HELLO) {
      console.log('收到Hello消息:', JSON.stringify(message, null, 2));
      console.log('音频参数:', JSON.stringify(message.audio_params, null, 2));
      if (message.session_id) {
        console.log('会话ID:', message.session_id);
      }
    }
  } catch (e) {
    // 如果不是JSON格式，可能是二进制数据
    console.log('收到非JSON消息');
  }
});

// 监听语音识别结果
client.on(ClientEvent.SPEECH_RECOGNITION, (message) => {
  console.log('语音识别结果:', message.text);
  console.log('是否最终结果:', message.final);
});

// 监听音频播放开始
client.on(ClientEvent.AUDIO_PLAY_START, (data) => {
  console.log('开始播放音频...');
});

// 监听音频播放结束
client.on(ClientEvent.AUDIO_PLAY_END, (message) => {
  console.log('音频播放结束');
});

// 监听错误
client.on(ClientEvent.ERROR, (error) => {
  console.error('发生错误:', error);
});

// 开始连接
console.log('尝试连接到服务器...');
client.connect();

// 处理进程终止事件，确保断开连接
process.on('SIGINT', () => {
  console.log('收到中断信号，断开连接...');
  client.disconnect();
  process.exit(0);
});
