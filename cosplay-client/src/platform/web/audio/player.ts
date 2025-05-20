import { AudioConfig } from '../../../types';
import { AudioPlayer } from '../../types';

/**
 * Web平台音频播放器实现
 * 使用Web Audio API播放音频
 */
export class WebAudioPlayer implements AudioPlayer {
  private audioContext: AudioContext | null = null;
  private isActive: boolean = false;
  private isPaused: boolean = false;
  private currentSource: AudioBufferSourceNode | null = null;
  private audioConfig: AudioConfig;
  private playbackEndCallback: (() => void) | null = null;
  
  /**
   * 构造函数
   * @param config 音频配置
   */
  constructor(config: AudioConfig) {
    this.audioConfig = {
      format: config.format || 'opus',
      sampleRate: config.sampleRate || 16000,
      channels: config.channels || 1,
      frameDuration: config.frameDuration || 20
    };
    
    // 创建音频上下文
    this.initAudioContext();
  }
  
  /**
   * 播放音频数据
   * @param data 音频数据
   * @returns 是否成功开始播放的Promise
   */
  public async play(data: ArrayBuffer): Promise<boolean> {
    if (!this.audioContext) {
      this.initAudioContext();
    }
    
    if (!this.audioContext) {
      console.error('Failed to create AudioContext');
      return false;
    }
    
    // 如果当前有正在播放的音频，先停止它
    this.stop();
    
    try {
      // 解码音频数据
      // 注意：如果数据是Opus格式，这里需要先解码
      // 由于Web Audio API不直接支持Opus，此处假设已经解码或是PCM
      let audioBuffer: AudioBuffer;
      
      if (this.audioConfig.format === 'opus') {
        // 在实际项目中，您需要添加Opus解码的逻辑
        // 可能需要使用WebAssembly库实现
        // 此处先将原始数据传递给decodeAudioData
        try {
          audioBuffer = await this.audioContext.decodeAudioData(data);
        } catch (e) {
          console.error('Failed to decode Opus data:', e);
          // 假设解码失败，可能是因为浏览器不支持格式
          // 在实际项目中，您需要处理这种情况
          return false;
        }
      } else {
        // PCM格式，需要将其转换为AudioBuffer
        audioBuffer = this.pcmToAudioBuffer(data);
      }
      
      // 创建音频源
      this.currentSource = this.audioContext.createBufferSource();
      this.currentSource.buffer = audioBuffer;
      
      // 连接到目标
      this.currentSource.connect(this.audioContext.destination);
      
      // 设置播放结束回调
      this.currentSource.onended = () => {
        this.isActive = false;
        if (this.playbackEndCallback) {
          this.playbackEndCallback();
        }
      };
      
      // 开始播放
      this.currentSource.start();
      this.isActive = true;
      this.isPaused = false;
      
      return true;
    } catch (error) {
      console.error('Failed to play audio:', error);
      return false;
    }
  }
  
  /**
   * 停止播放
   */
  public stop(): void {
    if (this.currentSource) {
      try {
        this.currentSource.stop();
      } catch (e) {
        // 忽略已停止的错误
      }
      this.currentSource = null;
    }
    
    this.isActive = false;
    this.isPaused = false;
  }
  
  /**
   * 暂停播放
   */
  public pause(): void {
    if (this.isActive && !this.isPaused && this.audioContext) {
      this.audioContext.suspend();
      this.isPaused = true;
    }
  }
  
  /**
   * 恢复播放
   */
  public resume(): void {
    if (this.isActive && this.isPaused && this.audioContext) {
      this.audioContext.resume();
      this.isPaused = false;
    }
  }
  
  /**
   * 检查是否正在播放
   */
  public isPlaying(): boolean {
    return this.isActive && !this.isPaused;
  }
  
  /**
   * 设置播放完成回调
   * @param callback 回调函数，播放完成时调用
   */
  public setPlaybackEndCallback(callback: () => void): void {
    this.playbackEndCallback = callback;
  }
  
  /**
   * 初始化音频上下文
   */
  private initAudioContext(): void {
    try {
      this.audioContext = new AudioContext({
        sampleRate: this.audioConfig.sampleRate
      });
    } catch (e) {
      console.error('Failed to create AudioContext:', e);
      this.audioContext = null;
    }
  }
  
  /**
   * 将PCM数据转换为AudioBuffer
   * @param pcmData PCM格式的音频数据
   * @returns AudioBuffer对象
   */
  private pcmToAudioBuffer(pcmData: ArrayBuffer): AudioBuffer {
    if (!this.audioContext) {
      throw new Error('AudioContext not initialized');
    }
    
    // 假设输入是16位PCM数据
    const int16Array = new Int16Array(pcmData);
    const float32Array = new Float32Array(int16Array.length);
    
    // 转换为-1.0到1.0的浮点数
    for (let i = 0; i < int16Array.length; i++) {
      // 将16位整数(-32768到32767)转换为浮点数(-1.0到1.0)
      float32Array[i] = int16Array[i] / (int16Array[i] < 0 ? 0x8000 : 0x7FFF);
    }
    
    // 创建AudioBuffer
    const audioBuffer = this.audioContext.createBuffer(
      this.audioConfig.channels || 1,
      float32Array.length,
      this.audioConfig.sampleRate || 16000
    );
    
    // 填充数据
    const channel = audioBuffer.getChannelData(0);
    channel.set(float32Array);
    
    return audioBuffer;
  }
}
