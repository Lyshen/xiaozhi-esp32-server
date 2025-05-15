import { AudioConfig, ClientConfig, ClientEvent, ConnectionState, ListeningState, MessageType } from './types';
import { Connection } from './core/connection/types';
import { DefaultConnectionFactory } from './core/connection/factory';
import { MessageHandler } from './core/protocol/handlers';
import { EventEmitter } from 'events';
import { AudioFactory, AudioPlayer, AudioRecorder } from './platform/types';
import { WebAudioFactory } from './platform/web/audio/factory';

/**
 * Cosplay客户端主类
 * 整合所有组件并提供统一的API
 */
export class CosplayClient {
  private config: ClientConfig;
  private connection: Connection;
  private eventEmitter: EventEmitter;
  private messageHandler: MessageHandler;
  private audioRecorder: AudioRecorder | null = null;
  private audioPlayer: AudioPlayer | null = null;
  private listeningState: ListeningState = ListeningState.IDLE;
  
  /**
   * 构造函数
   * @param config 客户端配置
   */
  constructor(config: ClientConfig) {
    // 合并默认配置
    this.config = {
      ...config,
      audioConfig: {
        format: 'pcm', // 默认使用PCM格式，更简单且广泛支持
        sampleRate: 16000,
        channels: 1,
        frameDuration: 20,
        ...config.audioConfig
      },
      reconnect: {
        enabled: true,
        maxAttempts: 10,
        delay: 1000,
        maxDelay: 30000,
        factor: 1.5,
        ...config.reconnect
      }
    };
    
    // 创建事件发射器
    this.eventEmitter = new EventEmitter();
    
    // 创建消息处理器
    this.messageHandler = new MessageHandler(this.eventEmitter);
    
    // 创建连接
    const connectionFactory = new DefaultConnectionFactory();
    this.connection = connectionFactory.createConnection(this.config);
    
    // 设置连接的事件处理
    this.connection.setMessageHandler(this.onMessage.bind(this));
    this.connection.setErrorHandler(this.onError.bind(this));
    this.connection.setStateChangeHandler(this.onConnectionStateChange.bind(this));
    
    // 初始化音频组件
    this.initializeAudioComponents();
  }
  
  /**
   * 初始化音频组件
   */
  private initializeAudioComponents(): void {
    try {
      const audioFactory: AudioFactory = new WebAudioFactory();
      
      if (audioFactory.isSupported()) {
        this.audioRecorder = audioFactory.createRecorder(this.config.audioConfig!);
        this.audioPlayer = audioFactory.createPlayer(this.config.audioConfig!);
        
        // 设置音频回调
        this.audioRecorder.setAudioCallback(this.onAudioData.bind(this));
        this.audioPlayer.setPlaybackEndCallback(() => {
          this.eventEmitter.emit(ClientEvent.AUDIO_PLAY_END);
        });
        
        // 监听音频事件
        this.eventEmitter.on(ClientEvent.AUDIO_PLAY_START, (data: ArrayBuffer) => {
          if (this.audioPlayer) {
            this.audioPlayer.play(data);
          }
        });
      } else {
        console.warn('Audio is not supported in the current environment');
      }
    } catch (error) {
      console.error('Failed to initialize audio components:', error);
    }
  }
  
  /**
   * 连接到服务器
   * @returns 连接是否成功的Promise
   */
  public async connect(): Promise<boolean> {
    try {
      const connected = await this.connection.connect();
      
      if (connected) {
        // 发送hello消息
        await this.sendHello();
      }
      
      return connected;
    } catch (error) {
      this.onError(error as Error);
      return false;
    }
  }
  
  /**
   * 断开连接
   */
  public disconnect(): void {
    try {
      // 停止录音
      this.stopListening();
      
      // 断开连接
      this.connection.disconnect();
    } catch (error) {
      console.error('Error disconnecting:', error);
    }
  }
  
  /**
   * 发送Hello消息
   */
  private async sendHello(): Promise<void> {
    const hello = {
      type: MessageType.HELLO,
      version: 1,
      transport: 'websocket',
      audio_params: {
        format: this.config.audioConfig?.format,
        sample_rate: this.config.audioConfig?.sampleRate,
        channels: this.config.audioConfig?.channels,
        frame_duration: this.config.audioConfig?.frameDuration
      }
    };
    
    await this.connection.sendText(JSON.stringify(hello));
  }
  
  /**
   * 开始录音并发送
   */
  public async startListening(): Promise<boolean> {
    if (!this.audioRecorder || this.listeningState !== ListeningState.IDLE) {
      return false;
    }
    
    try {
      const success = await this.audioRecorder.start();
      
      if (success) {
        this.listeningState = ListeningState.LISTENING;
        this.eventEmitter.emit(ClientEvent.SPEECH_START);
        
        // 发送listen消息
        await this.connection.sendText(JSON.stringify({
          type: MessageType.LISTEN,
          mode: 'auto'
        }));
      }
      
      return success;
    } catch (error) {
      console.error('Failed to start listening:', error);
      return false;
    }
  }
  
  /**
   * 停止录音
   */
  public stopListening(): void {
    if (!this.audioRecorder || this.listeningState !== ListeningState.LISTENING) {
      return;
    }
    
    try {
      this.audioRecorder.stop();
      this.listeningState = ListeningState.PROCESSING;
      this.eventEmitter.emit(ClientEvent.SPEECH_END);
      
      // 让处理完成后恢复idle状态
      setTimeout(() => {
        this.listeningState = ListeningState.IDLE;
      }, 1000);
    } catch (error) {
      console.error('Failed to stop listening:', error);
    }
  }
  
  /**
   * 发送文本消息
   * @param text 要发送的文本
   */
  public async sendText(text: string): Promise<void> {
    try {
      await this.connection.sendText(JSON.stringify({
        type: MessageType.TEXT,
        text: text
      }));
    } catch (error) {
      console.error('Failed to send text:', error);
    }
  }
  
  /**
   * 发送中止消息
   */
  public async sendAbort(): Promise<void> {
    try {
      await this.connection.sendText(JSON.stringify({
        type: MessageType.ABORT
      }));
    } catch (error) {
      console.error('Failed to send abort:', error);
    }
  }
  
  /**
   * 处理从录音机接收到的音频数据
   * @param data 音频数据
   */
  private onAudioData(data: ArrayBuffer): void {
    if (this.connection.getState() === ConnectionState.CONNECTED && 
        this.listeningState === ListeningState.LISTENING) {
      // 直接发送音频数据
      this.connection.sendBinary(data).catch(error => {
        console.error('Failed to send audio data:', error);
      });
    }
  }
  
  /**
   * 处理接收到的消息
   * @param data 消息数据
   */
  private onMessage(data: string | ArrayBuffer): void {
    this.messageHandler.handleMessage(data);
  }
  
  /**
   * 处理错误
   * @param error 错误对象
   */
  private onError(error: Error): void {
    console.error('Client error:', error);
    this.eventEmitter.emit(ClientEvent.ERROR, error);
  }
  
  /**
   * 处理连接状态变化
   * @param state 连接状态
   */
  private onConnectionStateChange(state: ConnectionState): void {
    console.log('Connection state changed:', state);
    
    switch (state) {
      case ConnectionState.CONNECTING:
        this.eventEmitter.emit(ClientEvent.CONNECTING);
        break;
        
      case ConnectionState.CONNECTED:
        this.eventEmitter.emit(ClientEvent.CONNECTED);
        break;
        
      case ConnectionState.DISCONNECTED:
        this.listeningState = ListeningState.IDLE;
        this.eventEmitter.emit(ClientEvent.DISCONNECTED);
        break;
        
      case ConnectionState.ERROR:
        this.listeningState = ListeningState.IDLE;
        this.eventEmitter.emit(ClientEvent.ERROR, new Error('Connection error'));
        break;
    }
  }
  
  /**
   * 注册事件监听器
   * @param event 事件名称
   * @param listener 监听函数
   */
  public on(event: string, listener: (...args: any[]) => void): void {
    this.eventEmitter.on(event, listener);
  }
  
  /**
   * 注册一次性事件监听器
   * @param event 事件名称
   * @param listener 监听函数
   */
  public once(event: string, listener: (...args: any[]) => void): void {
    this.eventEmitter.once(event, listener);
  }
  
  /**
   * 移除事件监听器
   * @param event 事件名称
   * @param listener 监听函数
   */
  public off(event: string, listener: (...args: any[]) => void): void {
    this.eventEmitter.removeListener(event, listener);
  }
  
  /**
   * 获取当前连接状态
   * @returns 连接状态
   */
  public getConnectionState(): ConnectionState {
    return this.connection.getState();
  }
  
  /**
   * 获取当前语音状态
   * @returns 语音状态
   */
  public getListeningState(): ListeningState {
    return this.listeningState;
  }
  
  /**
   * 获取当前会话ID
   * @returns 会话ID
   */
  public getSessionId(): string | null {
    return this.messageHandler.getSessionId();
  }
}
