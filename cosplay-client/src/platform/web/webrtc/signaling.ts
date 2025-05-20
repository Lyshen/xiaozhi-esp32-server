import { EventEmitter } from 'events';
import { SignalingMessage, SignalingMessageType, WebRTCEvent } from '../../../types/webrtc';

// 心跳配置
const HEARTBEAT_INTERVAL = 30000; // 30秒
const HEARTBEAT_TIMEOUT = 10000;  // 10秒

/**
 * WebRTC信令客户端
 * 负责处理客户端和服务器之间的信令消息
 */
export class SignalingClient {
  private url: string;
  private webSocket: WebSocket | null = null;
  private eventEmitter: EventEmitter;
  private reconnectAttempts: number = 0;
  private maxReconnectAttempts: number = 8; // 增加最大重试次数
  private reconnectTimeout: number = 2000;
  private connected: boolean = false;
  private heartbeatTimer: number | null = null;
  private heartbeatTimeoutTimer: number | null = null;
  private lastPongTime: number = 0;

  /**
   * 构造函数
   * @param url 信令服务器URL
   * @param eventEmitter 事件发射器
   */
  constructor(url: string, eventEmitter: EventEmitter) {
    this.url = url;
    this.eventEmitter = eventEmitter;
    // 添加客户端ID作为URL参数，如果URL中已有参数，则添加&，否则添加?
    if (this.url.indexOf('?') === -1) {
      this.url = `${this.url}?client_id=${this.generateClientId()}`;
    } else {
      this.url = `${this.url}&client_id=${this.generateClientId()}`;
    }
    console.log(`SignalingClient: URL配置为 ${this.url}`);
  }

  /**
   * 生成客户端ID
   * @returns 随机生成的客户端ID
   */
  private generateClientId(): string {
    return 'client_' + Math.random().toString(36).substring(2, 9);
  }

  /**
   * 连接到信令服务器
   * @returns 连接成功的Promise
   */
  public connect(): Promise<boolean> {
    return new Promise((resolve, reject) => {
      try {
        // 先确保没有活跃的WebSocket连接
        this.cleanupExistingConnection();
        
        // 创建WebSocket连接
        console.log(`SignalingClient: 正在尝试连接到信令服务器 URL: ${this.url}`);
        this.webSocket = new WebSocket(this.url);

        // 设置超时处理
        const connectionTimeout = setTimeout(() => {
          if (!this.connected && this.webSocket) {
            console.error('SignalingClient: 连接超时');
            this.webSocket.close();
            reject(new Error('Connection timeout'));
          }
        }, 10000); // 10秒超时

        // 连接建立时
        this.webSocket.onopen = () => {
          console.log('SignalingClient: Connected to signaling server');
          this.connected = true;
          this.reconnectAttempts = 0;
          clearTimeout(connectionTimeout);
          
          // 开始心跳
          this.startHeartbeat();
          
          resolve(true);
          
          // 通知连接状态改变
          this.eventEmitter.emit(WebRTCEvent.SIGNALING_CONNECTED);
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
        
      case SignalingMessageType.PING:
        // 收到服务器的ping，回复pong
        this.send({
          type: SignalingMessageType.PONG,
          payload: { timestamp: Date.now() }
        });
        break;
        
      case SignalingMessageType.PONG:
        // 收到服务器的pong
        this.lastPongTime = Date.now();
        if (this.heartbeatTimeoutTimer) {
          clearTimeout(this.heartbeatTimeoutTimer);
          this.heartbeatTimeoutTimer = null;
        }
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
  /**
   * 清理现有连接资源
   */
  private cleanupExistingConnection(): void {
    this.stopHeartbeat();
    
    if (this.webSocket) {
      // 移除所有事件监听器
      this.webSocket.onopen = null;
      this.webSocket.onmessage = null;
      this.webSocket.onclose = null;
      this.webSocket.onerror = null;
      
      // 如果连接还是打开的，优雅关闭
      if (this.webSocket.readyState === WebSocket.OPEN || 
          this.webSocket.readyState === WebSocket.CONNECTING) {
        this.webSocket.close();
      }
      this.webSocket = null;
    }
  }

  /**
   * 开始心跳检测
   */
  private startHeartbeat(): void {
    // 清理现有的心跳计时器
    this.stopHeartbeat();
    
    // 设置新的心跳计时器
    this.heartbeatTimer = window.setInterval(() => {
      if (this.connected && this.webSocket?.readyState === WebSocket.OPEN) {
        // 发送ping消息
        this.send({
          type: SignalingMessageType.PING,
          payload: { timestamp: Date.now() }
        });
        
        // 设置超时监测，如果在一定时间内没有收到pong，则认为连接已断开
        this.heartbeatTimeoutTimer = window.setTimeout(() => {
          console.warn('SignalingClient: 心跳超时，认为连接已断开');
          this.handleConnectionLost('心跳超时');
        }, HEARTBEAT_TIMEOUT);
      }
    }, HEARTBEAT_INTERVAL);
  }

  /**
   * 停止心跳检测
   */
  private stopHeartbeat(): void {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
    
    if (this.heartbeatTimeoutTimer) {
      clearTimeout(this.heartbeatTimeoutTimer);
      this.heartbeatTimeoutTimer = null;
    }
  }

  /**
   * 处理连接丢失
   */
  private handleConnectionLost(reason: string): void {
    console.error(`SignalingClient: 连接丢失 (${reason})`);
    this.connected = false;
    this.stopHeartbeat();
    this.cleanupExistingConnection();
    this.eventEmitter.emit(WebRTCEvent.SIGNALING_DISCONNECTED, reason);
    
    // 尝试重连
    this.handleReconnect();
  }
  
  /**
   * 断开连接
   */
  public disconnect(): void {
    this.stopHeartbeat();
    if (this.webSocket) {
      this.webSocket.close();
      this.webSocket = null;
    }
    this.connected = false;
    this.eventEmitter.emit(WebRTCEvent.SIGNALING_DISCONNECTED, '用户主动断开连接');
  }

  /**
   * 检查是否已连接
   * @returns 是否已连接
   */
  public isConnected(): boolean {
    return this.connected;
  }
}
