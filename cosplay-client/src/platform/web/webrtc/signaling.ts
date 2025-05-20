import { EventEmitter } from 'events';
import { SignalingMessage, SignalingMessageType, WebRTCEvent } from '../../../types/webrtc';

/**
 * WebRTC信令客户端
 * 负责处理客户端和服务器之间的信令消息
 */
export class SignalingClient {
  private url: string;
  private webSocket: WebSocket | null = null;
  private eventEmitter: EventEmitter;
  private reconnectAttempts: number = 0;
  private maxReconnectAttempts: number = 5;
  private reconnectTimeout: number = 2000;
  private connected: boolean = false;

  /**
   * 构造函数
   * @param url 信令服务器URL
   * @param eventEmitter 事件发射器
   */
  constructor(url: string, eventEmitter: EventEmitter) {
    this.url = url;
    this.eventEmitter = eventEmitter;
  }

  /**
   * 连接到信令服务器
   * @returns 连接成功的Promise
   */
  public connect(): Promise<boolean> {
    return new Promise((resolve, reject) => {
      try {
        // 创建WebSocket连接
        console.log(`SignalingClient: 正在尝试连接到信令服务器 URL: ${this.url}`);
        this.webSocket = new WebSocket(this.url);

        // 连接建立时
        this.webSocket.onopen = () => {
          console.log('SignalingClient: Connected to signaling server');
          this.connected = true;
          this.reconnectAttempts = 0;
          resolve(true);
        };

        // 接收消息时
        this.webSocket.onmessage = (event) => {
          try {
            const message = JSON.parse(event.data);
            this.handleMessage(message);
          } catch (error) {
            console.error('SignalingClient: Error parsing message:', error);
          }
        };

        // 连接关闭时
        this.webSocket.onclose = (event) => {
          this.connected = false;
          console.log(`SignalingClient: Connection closed (${event.code}): ${event.reason}`);
          this.handleReconnect();
        };

        // 连接错误时
        this.webSocket.onerror = (error) => {
          console.error('SignalingClient: Connection error:', error);
          reject(error);
        };
      } catch (error) {
        console.error('SignalingClient: Failed to connect:', error);
        reject(error);
      }
    });
  }

  /**
   * 处理接收到的消息
   * @param message 接收到的消息
   */
  private handleMessage(message: any): void {
    if (!message || !message.type) {
      console.warn('SignalingClient: Received invalid message format');
      return;
    }

    switch (message.type) {
      case SignalingMessageType.OFFER:
        this.eventEmitter.emit(SignalingMessageType.OFFER, message.payload);
        break;

      case SignalingMessageType.ANSWER:
        this.eventEmitter.emit(SignalingMessageType.ANSWER, message.payload);
        break;

      case SignalingMessageType.ICE_CANDIDATE:
        this.eventEmitter.emit(SignalingMessageType.ICE_CANDIDATE, message.payload);
        break;

      default:
        console.warn('SignalingClient: Unknown message type:', message.type);
    }
  }

  /**
   * 发送消息到信令服务器
   * @param message 要发送的消息
   * @returns 是否发送成功
   */
  public send(message: SignalingMessage): boolean {
    if (!this.connected || !this.webSocket) {
      console.error('SignalingClient: Cannot send message, not connected');
      console.error(`SignalingClient: Connection URL: ${this.url}, Connected status: ${this.connected}`);
      return false;
    }

    try {
      console.log(`SignalingClient: Sending message to ${this.url} (WebSocket readyState: ${this.webSocket.readyState})`);
      this.webSocket.send(JSON.stringify(message));
      return true;
    } catch (error) {
      console.error('SignalingClient: Error sending message:', error);
      return false;
    }
  }

  /**
   * 发送offer消息
   * @param offer SDP offer
   * @returns 是否发送成功
   */
  public sendOffer(offer: RTCSessionDescriptionInit): boolean {
    return this.send({
      type: SignalingMessageType.OFFER,
      payload: offer
    });
  }

  /**
   * 发送answer消息
   * @param answer SDP answer
   * @returns 是否发送成功
   */
  public sendAnswer(answer: RTCSessionDescriptionInit): boolean {
    return this.send({
      type: SignalingMessageType.ANSWER,
      payload: answer
    });
  }

  /**
   * 发送ICE候选信息
   * @param candidate ICE候选
   * @returns 是否发送成功
   */
  public sendIceCandidate(candidate: RTCIceCandidate): boolean {
    return this.send({
      type: SignalingMessageType.ICE_CANDIDATE,
      payload: candidate
    });
  }

  /**
   * 处理重连逻辑
   */
  private handleReconnect(): void {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.error(`SignalingClient: Max reconnect attempts (${this.maxReconnectAttempts}) reached`);
      this.eventEmitter.emit(WebRTCEvent.ERROR, new Error('Max reconnect attempts reached'));
      return;
    }

    this.reconnectAttempts++;
    const timeout = this.reconnectTimeout * Math.pow(1.5, this.reconnectAttempts - 1);
    console.log(`SignalingClient: Reconnecting in ${timeout}ms (attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts})`);

    setTimeout(() => {
      this.connect().catch(error => {
        console.error('SignalingClient: Reconnect failed:', error);
      });
    }, timeout);
  }

  /**
   * 断开连接
   */
  public disconnect(): void {
    if (this.webSocket) {
      this.webSocket.close();
      this.webSocket = null;
    }
    this.connected = false;
  }

  /**
   * 检查是否已连接
   * @returns 是否已连接
   */
  public isConnected(): boolean {
    return this.connected;
  }
}
