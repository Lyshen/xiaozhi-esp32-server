import { AudioConfig } from '../../../types';

// 定义全局MediaRecorder变量
const MediaRecorder = window.MediaRecorder;

/**
 * Opus编码器封装类
 * 用于对PCM音频数据进行Opus编码
 * 使用opus-media-recorder库替代opus-recorder和libopus，这是一个浏览器兼容的实现
 */
export class OpusEncoder {
  private mediaRecorder: any;
  private encodedCallback: ((data: ArrayBuffer) => void) | null = null;
  private isInitialized: boolean = false;
  private config: AudioConfig;
  private audioContext: AudioContext | null = null;
  private processor: ScriptProcessorNode | null = null;
  private sourceNode: MediaStreamAudioSourceNode | null = null;
  private audioStream: MediaStream | null = null;
  
  /**
   * 构造函数
   * @param config 音频配置
   * @param readyCallback 编码器准备就绪的回调
   */
  constructor(config: AudioConfig, readyCallback?: () => void) {
    this.config = config;
    
    // 检查是否支持opus-media-recorder
    try {
      if (!MediaRecorder) {
        throw new Error('MediaRecorder is not available');
      }
      
      if (!MediaRecorder.isTypeSupported('audio/ogg; codecs=opus')) {
        throw new Error('Opus codec is not supported in this browser');
      }
      
      // MediaRecorder 需要一个MediaStream，所以我们必须创建一个虚拟音频上下文
      this.setupAudioContext();
      
      // 延迟初始化，等待音频上下文就绪
      setTimeout(() => {
        this.initializeEncoder(readyCallback);
      }, 100);
      
    } catch (error) {
      console.error('Failed to initialize OpusMediaRecorder:', error);
      this.isInitialized = false;
      // 如果提供了回调，也要通知初始化失败
      if (readyCallback) {
        readyCallback();
      }
    }
  }
  
  /**
   * 设置音频上下文
   */
  private setupAudioContext(): void {
    try {
      // 创建一个AudioContext
      this.audioContext = new AudioContext({
        sampleRate: this.config.sampleRate || 16000
      });
      
      // 创建一个虚拟的音频节点
      const oscillator = this.audioContext.createOscillator();
      oscillator.frequency.value = 440; // 设置一个音频频率
      
      // 创建一个音频处理节点，用于将Float32Array数据输入到MediaRecorder
      this.processor = this.audioContext.createScriptProcessor(
        4096, // 缓冲区大小
        this.config.channels || 1, // 输入通道数
        this.config.channels || 1  // 输出通道数
      );
      
      // 将振荡器连接到处理器
      oscillator.connect(this.processor);
      
      // 创建一个MediaStream
      const destination = this.audioContext.createMediaStreamDestination();
      this.processor.connect(destination);
      
      // 保存流以供MediaRecorder使用
      this.audioStream = destination.stream;
      
      // 启动振荡器但立即断开，只是为了获取有效的MediaStream
      oscillator.start();
      oscillator.disconnect();
      
      console.log('Audio context setup completed');
    } catch (error) {
      console.error('Error setting up audio context:', error);
    }
  }
  
  /**
   * 初始化编码器
   * @param readyCallback 初始化完成回调
   */
  private initializeEncoder(readyCallback?: () => void): void {
    if (!this.audioStream) {
      console.error('Failed to initialize encoder: no audio stream available');
      return;
    }
    
    try {
      // 创建MediaRecorder实例，指定Opus编码
      this.mediaRecorder = new MediaRecorder(this.audioStream, {
        mimeType: 'audio/ogg; codecs=opus',
        audioBitsPerSecond: 32000 // 32kbps，与服务器端匹配
      });
      
      // 设置数据可用事件处理程序
      this.mediaRecorder.ondataavailable = (event: any) => {
        if (event.data && event.data.size > 0 && this.encodedCallback) {
          // 将Blob转换为ArrayBuffer
          const reader = new FileReader();
          reader.onload = () => {
            if (reader.result instanceof ArrayBuffer && this.encodedCallback) {
              // 这是完整的OGG容器，需要提取Opus数据
              this.extractOpusData(reader.result);
            }
          };
          reader.readAsArrayBuffer(event.data);
        }
      };
      
      // 开始录制，每60ms触发一次数据可用事件
      this.mediaRecorder.start(60);
      
      this.isInitialized = true;
      console.log('OpusMediaRecorder initialized successfully');
      
      if (readyCallback) {
        readyCallback();
      }
    } catch (error) {
      console.error('Failed to initialize OpusMediaRecorder:', error);
      this.isInitialized = false;
      
      if (readyCallback) {
        readyCallback();
      }
    }
  }
  
  /**
   * 从OGG容器中提取Opus数据
   * 注意：这是一个简化版本，真正的OGG解析更复杂
   * @param oggData OGG容器数据
   */
  private extractOpusData(oggData: ArrayBuffer): void {
    try {
      // 检查是否为OGG格式
      const dataView = new DataView(oggData);
      const isOgg = oggData.byteLength > 4 &&
                    dataView.getUint8(0) === 0x4F && // 'O'
                    dataView.getUint8(1) === 0x67 && // 'g'
                    dataView.getUint8(2) === 0x67 && // 'g'
                    dataView.getUint8(3) === 0x53;   // 'S'
      
      if (isOgg) {
        // 由于OGG解析比较复杂，这里我们直接发送整个OGG数据
        // 服务器端可能需要进行相应调整以处理OGG容器格式
        if (this.encodedCallback) {
          this.encodedCallback(oggData);
        }
      } else {
        console.warn('Received non-OGG data:', oggData.byteLength, 'bytes');
      }
    } catch (error) {
      console.error('Error extracting Opus data:', error);
    }
  }
  
  /**
   * 编码PCM音频数据
   * @param pcmData 浮点格式的PCM数据
   */
  public encode(pcmData: Float32Array): void {
    if (!this.isInitialized || !this.processor || !this.audioContext) {
      console.error('Encoder not initialized');
      return;
    }
    
    try {
      // 设置处理器的onaudioprocess处理程序，将PCM数据放入处理节点
      this.processor.onaudioprocess = (e: AudioProcessingEvent) => {
        const outputBuffer = e.outputBuffer;
        const outputData = outputBuffer.getChannelData(0);
        
        // 将输入数据复制到输出缓冲区
        for (let i = 0; i < pcmData.length && i < outputData.length; i++) {
          outputData[i] = pcmData[i];
        }
        
        // 只处理一次，然后移除处理程序
        this.processor!.onaudioprocess = null;
      };
    } catch (error) {
      console.error('Error encoding audio data:', error);
    }
  }
  
  /**
   * 将Float32Array转换为Int16Array (16位PCM)
   * 用于向下兼容或直接发送PCM数据
   * @param float32Array 浮点数组
   * @returns 16位整数数组
   */
  private floatTo16BitPCM(float32Array: Float32Array): Int16Array {
    const int16Array = new Int16Array(float32Array.length);
    for (let i = 0; i < float32Array.length; i++) {
      // 将-1.0 ~ 1.0的浮点值转换为-32768 ~ 32767的整数值
      const s = Math.max(-1, Math.min(1, float32Array[i]));
      int16Array[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
    }
    return int16Array;
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
    // 停止MediaRecorder
    if (this.mediaRecorder && this.mediaRecorder.state !== 'inactive') {
      try {
        this.mediaRecorder.stop();
      } catch (error) {
        console.error('Error stopping media recorder:', error);
      }
    }
    
    // 断开音频节点连接
    if (this.processor && this.audioContext) {
      try {
        this.processor.disconnect();
      } catch (error) {
        console.error('Error disconnecting processor:', error);
      }
    }
    
    // 关闭音频上下文
    if (this.audioContext && this.audioContext.state !== 'closed') {
      try {
        this.audioContext.close();
      } catch (error) {
        console.error('Error closing audio context:', error);
      }
    }
    
    // 清除所有引用
    this.mediaRecorder = null;
    this.processor = null;
    this.sourceNode = null;
    this.audioStream = null;
    this.audioContext = null;
    this.isInitialized = false;
    this.encodedCallback = null;
  }
}
