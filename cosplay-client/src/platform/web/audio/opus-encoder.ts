import { AudioConfig } from '../../../types';
import Recorder from 'opus-recorder';

/**
 * Opus编码器封装类
 * 用于对PCM音频数据进行Opus编码
 */
export class OpusEncoder {
  private recorder: any;
  private encodedCallback: ((data: ArrayBuffer) => void) | null = null;
  private isInitialized: boolean = false;
  private config: AudioConfig;
  private encodingQueue: Float32Array[] = [];
  private isProcessing: boolean = false;
  
  /**
   * 构造函数
   * @param config 音频配置
   * @param readyCallback 编码器准备就绪的回调
   */
  constructor(config: AudioConfig, readyCallback?: () => void) {
    this.config = config;
    
    // 创建Opus录制器实例，配置参数与服务器匹配
    this.recorder = new Recorder({
      encoderPath: '/opus-recorder/dist/encoderWorker.min.js', // 需要确保这个文件可访问
      encoderSampleRate: 16000, // 固定为16kHz以匹配服务器设置
      encoderApplication: 2048, // OPUS_APPLICATION_VOIP - 语音模式
      encoderFrameSize: 60,     // 960 samples = 60ms at 16kHz (服务器期望960个样本)
      encoderComplexity: 10,    // 高编码质量
      numberOfChannels: 1,      // 固定为单声道
      streamPages: true,        // 立即输出编码数据
      monitorGain: 0,           // 不监听
      originalSampleRateOverride: 16000, // 确保输入采样率正确
      maxBuffersPerPage: 1,     // 每次只输出一个缓冲区
      encoderBitRate: 16000,    // 16 kbps (低比特率适合语音)
    });
    
    // 设置数据可用回调
    this.recorder.ondataavailable = (arrayBuffer: ArrayBuffer) => {
      if (this.encodedCallback) {
        this.encodedCallback(arrayBuffer);
      }
    };
    
    // 设置错误回调
    this.recorder.onError = (error: any) => {
      console.error('Opus encoder error:', error);
    };
    
    // 初始化编码器
    this.initializeEncoder(readyCallback);
  }
  
  /**
   * 初始化编码器
   * @param readyCallback 初始化完成回调
   */
  private initializeEncoder(readyCallback?: () => void): void {
    try {
      // Opus-recorder初始化是异步的
      this.recorder.onready = () => {
        this.isInitialized = true;
        if (readyCallback) {
          readyCallback();
        }
        // 处理队列中的数据
        this.processEncodingQueue();
      };
      
      this.recorder.initWorker();
    } catch (error) {
      console.error('Failed to initialize Opus encoder:', error);
      this.isInitialized = false;
    }
  }
  
  /**
   * 编码PCM音频数据
   * @param pcmData 浮点格式的PCM数据
   */
  public encode(pcmData: Float32Array): void {
    if (!this.isInitialized) {
      // 如果编码器尚未初始化，将数据加入队列
      this.encodingQueue.push(pcmData);
      return;
    }
    
    try {
      // 直接传递浮点数据给编码器
      this.recorder.record(pcmData);
    } catch (error) {
      console.error('Opus encoding error:', error);
    }
  }
  
  /**
   * 处理编码队列
   */
  private processEncodingQueue(): void {
    if (this.isProcessing || this.encodingQueue.length === 0) {
      return;
    }
    
    this.isProcessing = true;
    
    try {
      // 处理队列中的所有数据
      while (this.encodingQueue.length > 0) {
        const data = this.encodingQueue.shift();
        if (data) {
          this.recorder.record(data);
        }
      }
    } catch (error) {
      console.error('Error processing encoding queue:', error);
    } finally {
      this.isProcessing = false;
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
    if (this.recorder) {
      try {
        this.recorder.close();
      } catch (error) {
        console.error('Error closing opus encoder:', error);
      }
    }
    
    this.encodingQueue = [];
    this.isInitialized = false;
    this.encodedCallback = null;
  }
}
