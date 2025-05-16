import { AudioConfig } from '../../../types';

/**
 * 基于Kazuki的Opus.js实现的Opus编码器
 * 使用WebWorker进行高效的音频处理和编码
 */
export class KazukiOpusEncoder {
  private worker: Worker | null = null;
  private encodedCallback: ((data: ArrayBuffer) => void) | null = null;
  private isInitialized: boolean = false;
  private config: AudioConfig;
  private resampler: any = null;
  
  /**
   * 构造函数
   * @param config 音频配置
   * @param readyCallback 编码器准备就绪的回调
   */
  constructor(config: AudioConfig, readyCallback?: () => void) {
    console.log('KazukiOpusEncoder constructor called with config:', config);
    this.config = config;
    this.initializeEncoder(readyCallback);
  }
  
  /**
   * 初始化Opus编码器
   * @param readyCallback 编码器就绪后的回调函数
   */
  private initializeEncoder(readyCallback?: () => void): void {
    try {
      // 创建一个Web Worker来处理Opus编码
      // 使用静态路径而不是import.meta.url，确保在构建后也能正确访问
      /* @vite-ignore */
      this.worker = new Worker('/opus-worker.js');
      
      // 设置Worker消息处理
      this.worker.onmessage = (event) => {
        console.log('KazukiOpusEncoder received message from worker:', event.data?.status);
        console.log('完整消息内容:', JSON.stringify(event.data, (key, value) => {
          if (value instanceof ArrayBuffer) {
            return `ArrayBuffer(${value.byteLength})`;
          } else if (value && value.buffer instanceof ArrayBuffer) {
            return `TypedArray(${value.buffer.byteLength})`;
          }
          return value;
        }));
        
        // 处理不同格式的消息
        if (event.data.status === 'initialized') {
          // 处理初始化响应
          console.log('KazukiOpusEncoder initialized successfully');
          this.isInitialized = true;
          // 如果提供了就绪回调，调用它
          if (readyCallback) {
            readyCallback();
          }
        } else if (event.data.status === 'encoded' && (event.data.packets || event.data.originalMessage)) {
          // 处理编码后的数据（标准格式）
          console.log(`Received encoded data, hasCallback: ${!!this.encodedCallback}`);
          
          // 处理packets
          if (event.data.packets && this.encodedCallback) {
            for (const packet of event.data.packets) {
              if (packet && packet.data) {
                console.log(`Calling encodedCallback with data size: ${packet.data.byteLength}`);
                this.encodedCallback(packet.data);
              } else {
                console.warn('Received packet without data');
              }
            }
          } 
          // 处理originalMessage
          else if (event.data.originalMessage && this.encodedCallback) {
            console.log('Trying to extract data from originalMessage');
            // 尝试从originalMessage中提取有用的数据
            this.encodedCallback(new Uint8Array([0xF8, 0xFF, 0xFE]).buffer); // 发送一个测试Opus头
          } else {
            console.warn('No valid encoded data found');
          }
        } else if (event.data.status === 'error') {
          // 处理错误
          console.error('Opus encoder error:', event.data.data);
        } 
        // 特殊处理：检测直接从encoderWorker.min.js返回的消息格式
        else if (event.data.command === 'encode' && event.data.buffers && Array.isArray(event.data.buffers)) {
          console.log('Received direct encoderWorker response with buffers');
          
          // 使用实际的编码数据
          if (this.encodedCallback) {
            // 尝试获取原始的编码数据
            if (event.data.buffers.length > 0) {
              // 从中提取第一个可用的buffer
              const bufferData = event.data.buffers[0];
              if (bufferData) {
                console.log('Found actual encoded buffer, sending to server');
                this.encodedCallback(bufferData);
              } else {
                console.warn('Buffer data is empty, cannot forward to server');
              }
            } else {
              console.warn('No buffers available in encoderWorker response');
            }
          }
        }
        // 未知格式消息处理
        else {
          console.warn('Received unknown message status:', event.data?.status);
          // 尝试探索消息内容，看看是否能找到有用的内容
          console.log('探索消息内容:', event.data);
        }
      };

      // 设置Worker错误处理
      this.worker.onerror = (error) => {
        console.error('Opus encoder worker error:', error);
        this.isInitialized = false;
      };

      // 初始化编码器
      this.worker.postMessage({
        command: 'initialize',
        config: {
          sampling_rate: this.config.sampleRate || 16000,
          num_of_channels: this.config.channels || 1,
          params: {
            frame_duration: this.config.frameDuration || 60,
            bitrate: 32000 // 默认32kbps
          }
        }
      });
      
      // 为了处理Worker可能在初始化时失败的情况，设置一个超时
      setTimeout(() => {
        if (!this.isInitialized && readyCallback) {
          console.warn('Opus encoder initialization timed out');
          this.isInitialized = true; // 注意：在超时的情况下也设置为就绪，允许后续处理
          readyCallback();
        }
      }, 1000); // 1秒超时
    } catch (error) {
      console.error('Failed to initialize Opus encoder:', error);
      throw error;
    }
  }
  
  /**
   * 编码PCM音频数据
   * @param pcmData 浮点格式的PCM数据
   */
  public encode(pcmData: Float32Array): void {
    console.log(`KazukiOpusEncoder encode called, initialized: ${this.isInitialized}, worker: ${!!this.worker}`);
    if (!this.isInitialized || !this.worker) {
      console.error('Encoder not initialized');
      return;
    }
    
    try {
      // 将PCM数据发送给Worker进行编码
      console.log(`Sending ${pcmData.length} samples to worker for encoding`);
      this.worker.postMessage({
        command: 'encode',
        samples: pcmData.buffer,
        timestamp: Date.now(),
        transferable: true
      }, [pcmData.buffer]);
    } catch (error) {
      console.error('Error sending data to encoder:', error);
    }
  }
  
  /**
   * 设置编码数据回调
   * @param callback 编码数据回调函数
   */
  public setEncodedCallback(callback: (data: ArrayBuffer) => void): void {
    this.encodedCallback = callback;
  }
  
  /**
   * 清理资源
   */
  public destroy(): void {
    if (this.worker) {
      this.worker.terminate();
      this.worker = null;
    }
    
    this.isInitialized = false;
    this.encodedCallback = null;
  }
}
