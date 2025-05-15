import { AudioConfig } from '../../../types';
import { AudioRecorder } from '../../types';

/**
 * Web平台音频录制器实现
 * 使用Web Audio API录制音频
 */
export class WebAudioRecorder implements AudioRecorder {
  private audioContext: AudioContext | null = null;
  private mediaStream: MediaStream | null = null;
  private sourceNode: MediaStreamAudioSourceNode | null = null;
  private processorNode: ScriptProcessorNode | null = null;
  private isActive: boolean = false;
  private isPaused: boolean = false;
  private audioConfig: AudioConfig;
  private audioCallback: ((data: ArrayBuffer) => void) | null = null;

  /**
   * 构造函数
   * @param config 音频配置
   */
  constructor(config: AudioConfig) {
    this.audioConfig = {
      format: config.format || 'pcm',
      sampleRate: config.sampleRate || 16000,
      channels: config.channels || 1,
      frameDuration: config.frameDuration || 20
    };
  }

  /**
   * 开始录音
   * @returns 是否成功开始录音的Promise
   */
  public async start(): Promise<boolean> {
    if (this.isActive) {
      return true;
    }

    try {
      // 请求麦克风访问权限
      this.mediaStream = await navigator.mediaDevices.getUserMedia({ 
        audio: {
          channelCount: this.audioConfig.channels,
          sampleRate: this.audioConfig.sampleRate 
        } 
      });
      
      // 创建音频上下文
      this.audioContext = new AudioContext({
        sampleRate: this.audioConfig.sampleRate
      });
      
      // 创建源节点
      this.sourceNode = this.audioContext.createMediaStreamSource(this.mediaStream);
      
      // 创建处理节点
      // 注意：ScriptProcessorNode已被废弃，但是AudioWorklet兼容性较差，所以此处仍使用ScriptProcessor
      this.processorNode = this.audioContext.createScriptProcessor(
        this.calculateBufferSize(),
        this.audioConfig.channels || 1,
        this.audioConfig.channels || 1
      );
      
      // 设置音频处理回调
      this.processorNode.onaudioprocess = this.handleAudioProcess.bind(this);
      
      // 连接节点
      this.sourceNode.connect(this.processorNode);
      this.processorNode.connect(this.audioContext.destination);
      
      this.isActive = true;
      this.isPaused = false;
      
      return true;
    } catch (error) {
      console.error('Failed to start audio recording:', error);
      this.cleanup();
      return false;
    }
  }

  /**
   * 停止录音
   */
  public stop(): void {
    this.cleanup();
  }

  /**
   * 暂停录音
   */
  public pause(): void {
    if (this.isActive && !this.isPaused) {
      this.isPaused = true;
      // 断开节点连接，暂停处理
      if (this.sourceNode && this.processorNode) {
        this.sourceNode.disconnect(this.processorNode);
      }
    }
  }

  /**
   * 恢复录音
   */
  public resume(): void {
    if (this.isActive && this.isPaused) {
      this.isPaused = false;
      // 重新连接节点，恢复处理
      if (this.sourceNode && this.processorNode) {
        this.sourceNode.connect(this.processorNode);
      }
    }
  }

  /**
   * This method returns whether the recorder is currently recording.
   * @returns a boolean indicating whether the recorder is recording
   */
  public isRecording(): boolean {
    return this.isActive && !this.isPaused;
  }

  /**
   * 设置音频数据回调
   * @param callback 回调函数，接收音频数据
   */
  public setAudioCallback(callback: (data: ArrayBuffer) => void): void {
    this.audioCallback = callback;
  }

  /**
   * 处理音频数据
   * @param event 音频处理事件
   */
  private handleAudioProcess(event: AudioProcessingEvent): void {
    if (!this.isActive || this.isPaused || !this.audioCallback) {
      return;
    }
    
    const inputBuffer = event.inputBuffer;
    const inputData = inputBuffer.getChannelData(0); // 获取第一个声道的数据
    
    // 根据音频格式处理数据
    if (this.audioConfig.format === 'pcm') {
      // 将Float32Array转换为16位PCM格式的Int16Array
      const pcmData = this.floatTo16BitPCM(inputData);
      this.audioCallback(pcmData.buffer);
    } else if (this.audioConfig.format === 'opus') {
      // 注意：这里我们只是将原始数据传递出去
      // 实际项目中，您需要添加Opus编码的逻辑，可能需要使用WebAssembly库实现
      // 由于Opus编码器的复杂性，此处先将原始PCM数据传递出去
      const pcmData = this.floatTo16BitPCM(inputData);
      this.audioCallback(pcmData.buffer);
    }
  }

  /**
   * 将Float32Array转换为Int16Array (16位PCM)
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
   * 计算适合的缓冲区大小
   * @returns 缓冲区大小
   */
  private calculateBufferSize(): number {
    const frameDuration = this.audioConfig.frameDuration || 20; // 默认20ms
    const sampleRate = this.audioConfig.sampleRate || 16000; // 默认16kHz
    
    // 计算每帧的样本数量
    const samplesPerFrame = Math.floor(sampleRate * frameDuration / 1000);
    
    // 找到最接近的2的幂次方值
    // WebAudio API要求缓冲区大小为2的幂次方，通常为256, 512, 1024, 2048, 4096, 8192, 16384
    const bufferSizes = [256, 512, 1024, 2048, 4096, 8192, 16384];
    let bestSize = bufferSizes[0];
    
    for (const size of bufferSizes) {
      if (size >= samplesPerFrame) {
        bestSize = size;
        break;
      }
    }
    
    return bestSize;
  }

  /**
   * 清理资源
   */
  private cleanup(): void {
    // 断开节点连接
    if (this.sourceNode && this.processorNode) {
      this.sourceNode.disconnect(this.processorNode);
      this.processorNode.disconnect();
    }
    
    // 停止MediaStream的所有轨道
    if (this.mediaStream) {
      this.mediaStream.getTracks().forEach(track => track.stop());
    }
    
    // 关闭AudioContext
    if (this.audioContext && this.audioContext.state !== 'closed') {
      this.audioContext.close();
    }
    
    // 重置所有对象
    this.audioContext = null;
    this.mediaStream = null;
    this.sourceNode = null;
    this.processorNode = null;
    this.isActive = false;
    this.isPaused = false;
  }
}
