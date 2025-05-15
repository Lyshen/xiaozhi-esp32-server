import { ClientEvent, Message, MessageType, SttMessage, TtsStatusMessage } from '../../types';
import { EventEmitter } from 'events';

/**
 * 消息处理器类，负责解析和处理WebSocket消息
 */
export class MessageHandler {
  private eventEmitter: EventEmitter;
  private sessionId: string | null = null;

  /**
   * 构造函数
   * @param eventEmitter 事件发射器
   */
  constructor(eventEmitter: EventEmitter) {
    this.eventEmitter = eventEmitter;
  }

  /**
   * 处理接收到的消息
   * @param data 消息数据
   */
  public handleMessage(data: string | ArrayBuffer): void {
    // 二进制数据（音频）
    if (data instanceof ArrayBuffer) {
      this.handleAudioData(data);
      return;
    }

    // 文本数据（JSON）
    try {
      const message = JSON.parse(data) as Message;
      this.handleJsonMessage(message);
    } catch (error) {
      console.error('Failed to parse message:', error);
    }
  }

  /**
   * 处理音频数据
   * @param data 音频数据
   */
  private handleAudioData(data: ArrayBuffer): void {
    // 发出音频数据事件，让播放器处理
    this.eventEmitter.emit(ClientEvent.AUDIO_PLAY_START, data);
  }

  /**
   * 处理JSON消息
   * @param message 消息对象
   */
  private handleJsonMessage(message: Message): void {
    // 发出一般消息事件
    this.eventEmitter.emit(ClientEvent.MESSAGE, message);

    // 根据消息类型处理
    switch (message.type) {
      case MessageType.HELLO:
        this.handleHelloMessage(message);
        break;
      case MessageType.STT:
        this.handleSttMessage(message as SttMessage);
        break;
      case MessageType.TTS:
        this.handleTtsMessage(message as TtsStatusMessage);
        break;
      // 可以添加更多消息类型的处理...
    }
  }

  /**
   * 处理Hello消息
   * @param message Hello消息
   */
  private handleHelloMessage(message: Message): void {
    console.log('Received hello message:', message);
    // 存储会话ID
    if (message.session_id) {
      this.sessionId = message.session_id;
    }
  }

  /**
   * 处理STT（语音转文字）消息
   * @param message STT消息
   */
  private handleSttMessage(message: SttMessage): void {
    // 发出语音识别事件
    this.eventEmitter.emit(ClientEvent.SPEECH_RECOGNITION, message.text, message.final);
  }

  /**
   * 处理TTS（文字转语音）状态消息
   * @param message TTS状态消息
   */
  private handleTtsMessage(message: TtsStatusMessage): void {
    switch (message.state) {
      case 'sentence_start':
        // TTS开始播放一个句子
        break;
      case 'sentence_end':
        // TTS结束播放一个句子
        break;
      case 'stop':
        // TTS完全停止
        this.eventEmitter.emit(ClientEvent.AUDIO_PLAY_END);
        break;
    }
  }

  /**
   * 获取当前会话ID
   * @returns 会话ID
   */
  public getSessionId(): string | null {
    return this.sessionId;
  }
}
