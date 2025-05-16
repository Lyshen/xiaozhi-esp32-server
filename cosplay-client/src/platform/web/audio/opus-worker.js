/**
 * Opus编码器Worker
 * 使用opus-recorder库处理音频编码
 */

// 全局变量
let encoder = null;
let initialized = false;
let config = {
  encoderSampleRate: 16000,
  encoderChannelCount: 1,
  encoderBitRate: 32000,
  encoderComplexity: 6
};

// 导入opus-recorder的encoderWorker脚本
try {
  importScripts('./encoderWorker.min.js');
  console.log('Successfully loaded encoderWorker.min.js');
} catch (e) {
  console.error('Failed to load encoderWorker.min.js:', e);
  self.postMessage({
    status: 'error',
    data: 'Failed to load encoderWorker.min.js: ' + e.message
  });
}

// 当encoder输出数据时的回调
self.onmessage = function(e) {
  if (e.data.page && e.data.page.buffer) {
    // 这是opus-recorder encoderWorker发送的编码后数据
    console.log('Received actual encoded Opus data from encoderWorker, size:', e.data.page.byteLength);
    
    // 将编码后的Opus数据发送回主线程
    self.postMessage({
      status: 'encoded',
      packets: [{ data: e.data.page.buffer }]
    }, [e.data.page.buffer]);
    return;
  }
  
  // 处理来自主线程的命令
  if (e.data.command === 'initialize') {
    // 存储配置
    if (e.data.config) {
      config.encoderSampleRate = e.data.config.sampling_rate || 16000;
      config.encoderChannelCount = e.data.config.num_of_channels || 1;
      config.encoderBitRate = e.data.config.bitrate || 32000;
      config.encoderComplexity = e.data.config.complexity || 6;
    }
    
    console.log('Initializing Opus encoder with config:', JSON.stringify(config));
    
    // 初始化opus-recorder编码器
    if (self.OpusEncoder) {
      try {
        encoder = new self.OpusEncoder(config);
        initialized = true;
        console.log('Opus encoder successfully initialized');
        
        self.postMessage({
          status: 'initialized'
        });
      } catch (err) {
        console.error('Error initializing Opus encoder:', err);
        self.postMessage({
          status: 'error',
          data: 'Failed to initialize Opus encoder: ' + err.message
        });
      }
    } else {
      // 使用原生的opus-recorder命令方式初始化
      self.postMessage({
        command: 'init',
        sampleRate: config.encoderSampleRate,
        channelCount: config.encoderChannelCount,
        bitsPerSecond: config.encoderBitRate,
        complexity: config.encoderComplexity
      });
      
      initialized = true;
      console.log('Sent init command to opus-recorder encoderWorker');
      
      self.postMessage({
        status: 'initialized'
      });
    }
  } 
  else if (e.data.command === 'encode') {
    if (!initialized) {
      self.postMessage({
        status: 'error',
        data: 'Encoder not initialized'
      });
      return;
    }

    try {
      // 提取音频样本数据
      const float32Samples = new Float32Array(e.data.samples);
      console.log(`Encoding ${float32Samples.length} audio samples`);

      if (encoder) {
        // 如果我们有自己的编码器实例，直接使用它
        const encodedData = encoder.encode(float32Samples);
        
        // 将编码后的数据发送回主线程
        self.postMessage({
          status: 'encoded',
          packets: [{ data: encodedData.buffer }]
        }, [encodedData.buffer]);
      } else {
        // 否则使用原生opus-recorder命令方式
        self.postMessage({
          command: 'encode',
          buffers: [float32Samples.buffer]
        }, [float32Samples.buffer]);
      }
    } catch (error) {
      console.error('Error encoding audio data:', error);
      self.postMessage({
        status: 'error',
        data: 'Encoding error: ' + error.message
      });
    }
  }
  else if (e.data.command === 'close') {
    console.log('Closing encoder worker');
    
    if (encoder) {
      try {
        encoder.destroy();
      } catch (e) {
        console.warn('Error destroying encoder:', e);
      }
    } else {
      // 告知opus-recorder关闭
      self.postMessage({ command: 'done' });
    }
    
    self.postMessage({
      status: 'closed'
    });
  }
  else {
    // 检查是否是opus-recorder的其他消息
    const isOpusRecorderMessage = e.data && 
      (typeof e.data === 'object') && 
      (e.data.command || e.data.message || e.data.page || e.data.buffer);
    
    if (isOpusRecorderMessage) {
      console.log('Received opus-recorder internal message:', JSON.stringify(e.data, (key, value) => {
        if (value instanceof ArrayBuffer) {
          return `ArrayBuffer(${value.byteLength})`;
        } else if (value && value.buffer instanceof ArrayBuffer) {
          return `TypedArray(${value.buffer.byteLength})`;
        }
        return value;
      }));
    } else {
      console.warn('Unknown command:', e.data);
    }
  }
};
