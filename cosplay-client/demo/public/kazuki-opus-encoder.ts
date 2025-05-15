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
        console.log('KazukiOpusEncoder received message from worker:', event.data.status);
        const { status, packets, data } = event.data;

        if (status === 'initialized') {
          console.log('KazukiOpusEncoder initialized successfully');
          this.isInitialized = true;
          // 如果提供了就绪回调，调用它
          if (readyCallback) {
            readyCallback();
          }
        } else if (status === 'encoded' && packets) {
          console.log(`Received encoded data from worker: ${packets.length} packets, hasCallback: ${!!this.encodedCallback}`);
          // 如果收到编码后的数据包，调用回调将数据发送出去
          if (this.encodedCallback) {
            for (const packet of packets) {
              if (packet && packet.data) {
                console.log(`Calling encodedCallback with data size: ${packet.data.byteLength}`);
                this.encodedCallback(packet.data);
              } else {
                console.warn('Received packet without data');
              }
            }
          } else {
            console.warn('No encodedCallback set to handle encoded data');
          }
        } else if (status === 'error') {
          console.error('Opus encoder error:', data);
        } else {
          console.warn('Received unknown message status:', status);
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
