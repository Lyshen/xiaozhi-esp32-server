import { EventEmitter } from 'events';
import { WebRTCEvent } from '../../../types/webrtc';

/**
 * WebRTC媒体管理器
 * 负责管理媒体流的获取、处理和释放
 */
export class MediaManager {
  private localStream: MediaStream | null = null;
  private audioContext: AudioContext | null = null;
  private mediaSource: MediaStreamAudioSourceNode | null = null;
  private audioProcessor: ScriptProcessorNode | null = null;
  private eventEmitter: EventEmitter;
  private isProcessing: boolean = false;
  private audioCallback: ((data: ArrayBuffer) => void) | null = null;

  /**
   * 构造函数
   * @param eventEmitter 事件发射器
   */
  constructor(eventEmitter: EventEmitter) {
    this.eventEmitter = eventEmitter;
  }

  /**
   * 获取本地媒体流
   * @param constraints 媒体约束
   * @returns 包含本地媒体流的Promise
   */
  public async getLocalStream(constraints: MediaStreamConstraints): Promise<MediaStream> {
    if (this.localStream) {
      return this.localStream;
    }

    try {
      // 确保只请求音频
      const finalConstraints: MediaStreamConstraints = {
        audio: constraints.audio || true,
        video: false
      };

      // 获取媒体流
      this.localStream = await navigator.mediaDevices.getUserMedia(finalConstraints);
      console.log('MediaManager: Local media stream obtained');
      
      return this.localStream;
    } catch (error) {
      console.error('MediaManager: Error getting local media stream:', error);
      throw error;
    }
  }

  /**
   * 停止并释放本地媒体流
   */
  public stopLocalStream(): void {
    if (this.localStream) {
      this.localStream.getTracks().forEach(track => {
        track.stop();
      });
      this.localStream = null;
      console.log('MediaManager: Local media stream stopped');
    }
  }

  /**
   * 初始化音频处理
   * @param sampleRate 采样率
   * @returns 是否初始化成功
   */
  public initAudioProcessing(sampleRate: number = 16000): boolean {
    if (!this.localStream) {
      console.error('MediaManager: Cannot initialize audio processing without a local stream');
      return false;
    }

    try {
      // 创建音频上下文
      this.audioContext = new (window.AudioContext || (window as any).webkitAudioContext)({
        sampleRate: sampleRate
      });

      // 创建媒体源节点
      this.mediaSource = this.audioContext.createMediaStreamSource(this.localStream);

      // 创建处理节点
      // 注：ScriptProcessorNode已被标记为废弃，将来可能需要迁移到AudioWorklet
      this.audioProcessor = this.audioContext.createScriptProcessor(4096, 1, 1);
      this.audioProcessor.onaudioprocess = this.handleAudioProcess.bind(this);

      // 连接节点
      this.mediaSource.connect(this.audioProcessor);
      this.audioProcessor.connect(this.audioContext.destination);

      this.isProcessing = true;
      console.log('MediaManager: Audio processing initialized');
      return true;
    } catch (error) {
      console.error('MediaManager: Failed to initialize audio processing:', error);
      return false;
    }
  }

  /**
   * 处理音频数据
   * @param event 音频处理事件
   */
  private handleAudioProcess(event: AudioProcessingEvent): void {
    if (!this.isProcessing) return;

    // 获取输入缓冲区
    const inputBuffer = event.inputBuffer;
    const inputData = inputBuffer.getChannelData(0);

    // 转换为16bit PCM
    const pcmData = this.floatTo16BitPCM(inputData);

    // 如果设置了回调，则调用回调
    if (this.audioCallback) {
      this.audioCallback(pcmData.buffer);
    }

    // 发出事件
    this.eventEmitter.emit(WebRTCEvent.AUDIO_SENT, pcmData.buffer);
  }

  /**
   * 将Float32Array转换为Int16Array (16bit PCM)
   * @param input Float32Array输入
   * @returns Int16Array (16bit PCM)
   */
  private floatTo16BitPCM(input: Float32Array): Int16Array {
    const output = new Int16Array(input.length);
    for (let i = 0; i < input.length; i++) {
      // 将-1.0到1.0的浮点数转换为-32768到32767的整数
      const s = Math.max(-1, Math.min(1, input[i]));
      output[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
    }
    return output;
  }

  /**
   * 停止音频处理
   */
  public stopAudioProcessing(): void {
    this.isProcessing = false;

    if (this.audioProcessor) {
      this.audioProcessor.disconnect();
      this.audioProcessor = null;
    }

    if (this.mediaSource) {
      this.mediaSource.disconnect();
      this.mediaSource = null;
    }

    if (this.audioContext && this.audioContext.state !== 'closed') {
      this.audioContext.close();
      this.audioContext = null;
    }

    console.log('MediaManager: Audio processing stopped');
  }

  /**
   * 设置音频数据回调
   * @param callback 音频数据回调函数
   */
  public setAudioCallback(callback: (data: ArrayBuffer) => void): void {
    this.audioCallback = callback;
  }

  /**
   * 释放所有资源
   */
  public dispose(): void {
    this.stopAudioProcessing();
    this.stopLocalStream();
  }
}
