import { AudioConfig, AudioRecorderState } from '../../../types';
import { AudioRecorder } from '../../types';
import { WebRTCFactory } from '../webrtc/factory';
import { WebRTCAudioConnection } from '../webrtc/audio-connection';
import { WebRTCEvent, WebRTCConnectionState } from '../../../types/webrtc';

/**
 * 基于WebRTC的录音机实现
 * 使用WebRTC API进行音频捕获和处理
 */
export class WebRTCRecorder implements AudioRecorder {
  private config: AudioConfig;
  private state: AudioRecorderState = AudioRecorderState.INACTIVE;
  private audioCallback: ((data: ArrayBuffer) => void) | null = null;
  private webrtcConnection: WebRTCAudioConnection | null = null;
  private isConnected: boolean = false;
  private recording: boolean = false;

  /**
   * 构造函数
   * @param config 音频配置
   */
  constructor(config: AudioConfig) {
    this.config = config;
  }

  /**
   * 初始化录音机
   * @returns 是否成功的Promise
   */
  public async initialize(): Promise<boolean> {
    try {
      console.log('WebRTCRecorder: Beginning initialization with config:', JSON.stringify(this.config, null, 2));
      
      // 检查是否支持WebRTC
      if (!WebRTCFactory.isSupported()) {
        console.error('WebRTCRecorder: WebRTC is not supported in the current environment');
        return false;
      }
      
      console.log('WebRTCRecorder: WebRTC is supported, creating audio connection');

      // 创建WebRTC音频连接
      const signalingUrl = this.config.webrtcSignalingUrl || 'wss://xiaozhi.qiniu.io/ws/signaling';
      console.log('WebRTCRecorder: Using signaling URL:', signalingUrl);
      
      this.webrtcConnection = WebRTCFactory.createAudioConnection({
        iceServers: [
          { urls: 'stun:stun.l.google.com:19302' },
          { urls: 'stun:stun1.l.google.com:19302' }
        ],
        mediaConstraints: {
          audio: {
            echoCancellation: this.config.echoCancellation !== false,
            noiseSuppression: this.config.noiseSuppression !== false,
            autoGainControl: this.config.autoGainControl !== false
          },
          video: false
        },
        sampleRate: this.config.sampleRate || 16000,
        signalingUrl: signalingUrl
      });

      // 设置事件监听
      this.setupEventListeners();

      // 初始化WebRTC连接
      await this.webrtcConnection.initialize();

      // 如果设置了音频回调，则传递给WebRTC连接
      if (this.audioCallback) {
        this.webrtcConnection.setAudioCallback(this.audioCallback);
      }

      this.state = AudioRecorderState.INITIALIZED;
      console.log('WebRTCRecorder: Initialized successfully');
      return true;
    } catch (error) {
      console.error('WebRTCRecorder: Initialization failed:', error);
      return false;
    }
  }

  /**
   * 设置WebRTC事件监听器
   */
  private setupEventListeners(): void {
    if (!this.webrtcConnection) return;

    // 连接状态变化
    this.webrtcConnection.on(WebRTCEvent.CONNECTED, () => {
      this.isConnected = true;
      console.log('WebRTCRecorder: WebRTC connection established');
    });

    this.webrtcConnection.on(WebRTCEvent.DISCONNECTED, () => {
      this.isConnected = false;
      console.log('WebRTCRecorder: WebRTC connection closed');
      
      // 如果正在录音，则停止录音
      if (this.state === AudioRecorderState.RECORDING) {
        this.stop();
      }
    });

    this.webrtcConnection.on(WebRTCEvent.ERROR, (error: Error) => {
      console.error('WebRTCRecorder: WebRTC error:', error);
      
      // 如果正在录音，则停止录音
      if (this.state === AudioRecorderState.RECORDING) {
        this.stop();
      }
    });
  }

  /**
   * 开始录音
   * @returns 是否成功的Promise
   */
  public async start(): Promise<boolean> {
    if (this.state === AudioRecorderState.RECORDING) {
      console.warn('WebRTCRecorder: Already recording');
      return true;
    }

    if (!this.webrtcConnection) {
      try {
        const initialized = await this.initialize();
        if (!initialized) {
          return false;
        }
      } catch (error) {
        console.error('WebRTCRecorder: Failed to initialize:', error);
        return false;
      }
    }

    try {
      // 如果尚未连接，则创建offer
      if (!this.isConnected && this.webrtcConnection) {
        const offerCreated = await this.webrtcConnection.createOffer();
        if (!offerCreated) {
          console.error('WebRTCRecorder: Failed to create offer');
          return false;
        }
      }

      this.state = AudioRecorderState.RECORDING;
      this.recording = true;
      console.log('WebRTCRecorder: Recording started');
      return true;
    } catch (error) {
      console.error('WebRTCRecorder: Failed to start recording:', error);
      return false;
    }
  }

  /**
   * 停止录音
   * @returns 是否成功
   */
  public stop(): boolean {
    if (this.state !== AudioRecorderState.RECORDING) {
      console.warn('WebRTCRecorder: Not recording');
      return false;
    }

    this.state = AudioRecorderState.INACTIVE;
    this.recording = false;
    console.log('WebRTCRecorder: Recording stopped');
    return true;
  }

  /**
   * 设置音频数据回调
   * @param callback 音频数据回调函数
   */
  public setAudioCallback(callback: (data: ArrayBuffer) => void): void {
    this.audioCallback = callback;
    
    if (this.webrtcConnection) {
      this.webrtcConnection.setAudioCallback(callback);
    }
  }

  /**
   * 获取当前状态
   * @returns 当前状态
   */
  public getState(): AudioRecorderState {
    return this.state;
  }

  /**
   * 暂停录音
   */
  public pause(): void {
    if (this.state !== AudioRecorderState.RECORDING) {
      console.warn('WebRTCRecorder: Not recording, cannot pause');
      return;
    }

    this.state = AudioRecorderState.PAUSED;
    console.log('WebRTCRecorder: Recording paused');
  }

  /**
   * 恢复录音
   */
  public resume(): void {
    if (this.state !== AudioRecorderState.PAUSED) {
      console.warn('WebRTCRecorder: Not paused, cannot resume');
      return;
    }

    this.state = AudioRecorderState.RECORDING;
    console.log('WebRTCRecorder: Recording resumed');
  }

  /**
   * 检查是否正在录音
   * @returns 是否正在录音
   */
  public isRecording(): boolean {
    return this.recording;
  }

  /**
   * 释放资源
   */
  public dispose(): void {
    if (this.webrtcConnection) {
      this.webrtcConnection.disconnect();
      this.webrtcConnection = null;
    }

    this.state = AudioRecorderState.INACTIVE;
    this.recording = false;
    console.log('WebRTCRecorder: Disposed');
  }
}
