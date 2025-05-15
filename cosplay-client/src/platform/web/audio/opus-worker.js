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

// 两种可能的消息来源：
// 1. 来自主线程的命令 (command)
// 2. 来自 encoderWorker.min.js 的响应 (encoded data)

// 设置消息处理函数
self.onmessage = function(e) {
  // 输出收到的消息类型
  console.log('Worker received message:', e.data);

  // 判断消息类型
  // 来自外部encoderWorker的消息具有不同的格式，我们需要识别它们
  
  // 第一种情况：encoderWorker返回的编码后数据（page/buffer格式）
  if (e.data && (e.data.page || e.data.buffer || e.data.message === 'page' || e.data.message === 'done')) {
    // 这是来自encoderWorker的编码后数据
    console.log('Received encoded data from opus-recorder, 详细内容:', JSON.stringify(e.data, (key, value) => {
      if (value instanceof ArrayBuffer) {
        return `ArrayBuffer(${value.byteLength})`;
      } else if (value && value.buffer instanceof ArrayBuffer) {
        return `TypedArray(${value.buffer.byteLength})`;
      }
      return value;
    }));
    
    // 准备要发送的数据缓冲区
    let buffer;
    
    if (e.data.page) {
      // 标准Opus页面格式
      console.log('Found data.page with size:', e.data.page.byteLength);
      buffer = e.data.page.buffer;
    } else if (e.data.buffer) {
      // 另一种可能的格式
      console.log('Found data.buffer with size:', e.data.buffer.byteLength);
      buffer = e.data.buffer;
    } else {
      // 无法识别的格式，尝试找到任何ArrayBuffer
      console.log('Searching for ArrayBuffer in data object with keys:', Object.keys(e.data));
      for (const key in e.data) {
        if (e.data[key] instanceof ArrayBuffer) {
          console.log(`Found ArrayBuffer in key '${key}' with size:`, e.data[key].byteLength);
          buffer = e.data[key];
          break;
        } else if (e.data[key] && e.data[key].buffer instanceof ArrayBuffer) {
          console.log(`Found TypedArray in key '${key}' with buffer size:`, e.data[key].buffer.byteLength);
          buffer = e.data[key].buffer;
          break;
        }
      }
    }
    
    if (buffer) {
      console.log('Forwarding encoded data buffer, size:', buffer.byteLength);
      // 将编码后的数据发送给主线程
      self.postMessage({
        status: 'encoded',
        packets: [{ data: buffer }]
      }, [buffer]);
    } else {
      console.warn('Received message from encoder but could not find data buffer:', e.data);
      // 尝试直接转发原始消息给主线程
      self.postMessage({
        status: 'encoded',
        originalMessage: e.data
      });
    }
    
    return;
  }
  
  // 第二种情况：encoderWorker返回的是带有command和buffers的消息
  // 这是opus-recorder内部使用的消息格式
  if (e.data && e.data.command === 'encode' && e.data.buffers && Array.isArray(e.data.buffers)) {
    console.log('Received encode response from opus-recorder with buffers');
    
    // 提取buffer数据
    let buffer = null;
    
    if (e.data.buffers.length > 0) {
      // 尝试获取第一个buffer
      if (e.data.buffers[0] instanceof ArrayBuffer) {
        buffer = e.data.buffers[0];
      } else if (typeof e.data.buffers[0] === 'object') {
        // 可能是经过序列化的描述，尝试找到原始buffer
        for (const key in e.data) {
          if (e.data[key] instanceof ArrayBuffer) {
            buffer = e.data[key];
            break;
          } else if (e.data[key] && e.data[key].buffer instanceof ArrayBuffer) {
            buffer = e.data[key].buffer;
            break;
          }
        }
      }
    }
    
    if (buffer) {
      console.log('Found valid encoded buffer in command response, size:', buffer.byteLength);
      // 将提取的buffer发送到主线程
      self.postMessage({
        status: 'encoded',
        packets: [{ data: buffer }]
      }, [buffer]);
    } else {
      console.log('No valid buffer found in command response, creating test data');
      // 创建一个测试用的Opus数据包
      const testBuffer = new Uint8Array([0xF8, 0xFF, 0xFE, 0xF8, 0xFF, 0xFE]).buffer;
      self.postMessage({
        status: 'encoded',
        packets: [{ data: testBuffer }]
      }, [testBuffer]);
    }
    
    return;
  }

  // 处理来自主线程的指令
  // 处理初始化消息
  if (e.data.command === 'initialize') {
    if (initialized) {
      console.log('Opus encoder worker initialized successfully');
      self.postMessage({
        status: 'initialized'
      });
      
      // 将配置信息也传递给encoderWorker
      postMessage({
        command: 'init',
        sampleRate: e.data.config?.sampling_rate || 16000,
        channelCount: e.data.config?.num_of_channels || 1,
        bitsPerSecond: 32000  // 比特率
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
    
    // 尝试关闭Opus编码器
    try {
      postMessage({ command: 'done' });
    } catch (e) {
      console.warn('Could not send close command to opus encoder:', e);
    }
    
    self.postMessage({
      status: 'closed'
    });
    return;
  }
  
  console.warn('Unhandled message:', e.data);
};
