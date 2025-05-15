/**
 * 简化版opus-recorder集成的Worker代理
 * 直接引入encoderWorker.min.js，并处理消息转发
 */

// 全局变量
let originalOnMessage;
let initialized = false;

// 保存原始onmessage处理函数
if (typeof self.onmessage === 'function') {
  originalOnMessage = self.onmessage;
}

// 先加载原始Worker脚本
try {
  importScripts('./encoderWorker.min.js');
  console.log('Successfully loaded encoderWorker.min.js');
  
  // 初始化成功
  initialized = true;
} catch (e) {
  console.error('Failed to load encoderWorker.min.js:', e);
  // 发送错误消息给主线程
  self.postMessage({
    status: 'error',
    data: 'Failed to load encoderWorker.min.js: ' + e.message
  });
}

// 设置消息处理函数
self.onmessage = function(e) {
  // 输出收到的消息类型
  console.log('Worker received message:', e.data);

  // 处理初始化消息
  if (e.data.command === 'initialize') {
    if (initialized) {
      console.log('Opus encoder worker initialized successfully');
      self.postMessage({
        status: 'initialized'
      });
    } else {
      self.postMessage({
        status: 'error',
        data: 'Failed to initialize opus encoder'
      });
    }
    return;
  }
  
  // 应答音频数据
  if (e.data.command === 'encode') {
    if (!initialized) {
      self.postMessage({
        status: 'error',
        data: 'Encoder not initialized'
      });
      return;
    }

    try {
      // 将消息转发给原始编码器Worker
      // encoderWorker.min.js预期收到的格式
      const float32Samples = new Float32Array(e.data.samples);
      console.log(`Encoding ${float32Samples.length} audio samples`);
      
      postMessage({
        command: 'encode',
        buffers: [float32Samples.buffer]
      }, [float32Samples.buffer]);
    } catch (error) {
      console.error('Error in encoding:', error);
      self.postMessage({
        status: 'error',
        data: 'Encoding error: ' + error.message
      });
    }
    return;
  }
  
  // 处理关闭请求
  if (e.data.command === 'close') {
    console.log('Closing encoder worker');
    self.postMessage({
      status: 'closed'
    });
    return;
  }
  
  // 处理来自底层Worker的响应
  if (e.data.message === 'page') {
    // 将编码后的数据发送给主线程
    console.log('Received encoded data, size:', e.data.page.byteLength);
    self.postMessage({
      status: 'encoded',
      packets: [{ data: e.data.page.buffer }]
    }, [e.data.page.buffer]);
    return;
  }
};
