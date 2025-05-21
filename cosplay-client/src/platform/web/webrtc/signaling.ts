import { EventEmitter } from 'events';
import { SignalingMessage, SignalingMessageType, WebRTCEvent } from '../../../types/webrtc';

// 心跳配置
const HEARTBEAT_INTERVAL = 15000; // 15秒
const HEARTBEAT_TIMEOUT = 8000;   // 8秒
const MAX_RECONNECT_ATTEMPTS = 10; // 最大重连次数
const INITIAL_RECONNECT_DELAY = 1000; // 初始重连延迟（毫秒）
const LOG_HEARTBEAT_FREQUENCY = 10; // 每10次心跳打印一次日志

/**
 * WebRTC信令客户端
 * 负责处理客户端和服务器之间的信令消息
 */
export class SignalingClient {
  private url: string;
  private webSocket: WebSocket | null = null;
  private eventEmitter: EventEmitter;
  private reconnectAttempts: number = 0;
  private maxReconnectAttempts: number = MAX_RECONNECT_ATTEMPTS;
  private reconnectTimeout: number = INITIAL_RECONNECT_DELAY;
  private connected: boolean = false;
  private heartbeatTimer: number | null = null;
  private heartbeatTimeoutTimer: number | null = null;
  private lastPongTime: number = 0;
  private heartbeatCount: number = 0;
  private messagesSent: number = 0;
  private messagesReceived: number = 0;
  private instanceId: string = Math.random().toString(36).substring(2, 9);
  private sessionId: string;

  /**
   * 构造函数
   * @param url 信令服务器URL
   * @param eventEmitter 事件发射器
   * @param sessionId 可选的会话ID，用于在信令和WebRTC连接间保持一致的身份
   */
  constructor(url: string, eventEmitter: EventEmitter, sessionId?: string) {
    this.url = url;
    this.eventEmitter = eventEmitter;
    
    // 使用提供的sessionId或生成新的客户端ID
    const clientId = sessionId || this.generateClientId();
    
    // 添加客户端ID作为URL参数，如果URL中已有参数，则添加&，否则添加?
    if (this.url.indexOf('?') === -1) {
      this.url = `${this.url}?client_id=${clientId}`;
    } else {
      this.url = `${this.url}&client_id=${clientId}`;
    }
    
    // 保存会话ID，用于后续通信
    this.sessionId = clientId;
    console.log(`SignalingClient[${this.instanceId}]: 初始化，URL配置为 ${this.url}`);
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
        console.log(`SignalingClient[${this.instanceId}]: 正在尝试连接到信令服务器 URL: ${this.url}`);
        this.webSocket = new WebSocket(this.url);

        // 设置超时处理
        const connectionTimeout = setTimeout(() => {
          if (!this.connected && this.webSocket) {
            console.error(`SignalingClient[${this.instanceId}]: 连接超时`);
            this.webSocket.close();
            reject(new Error('Connection timeout'));
          }
        }, 10000); // 10秒超时

        // 连接建立时
        this.webSocket.onopen = () => {
          console.log(`SignalingClient[${this.instanceId}]: 已连接到信令服务器，WebSocket状态: ${this.webSocket?.readyState}`);
          this.connected = true;
          this.reconnectAttempts = 0;
          this.messagesSent = 0;
          this.messagesReceived = 0;
          this.heartbeatCount = 0;
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
            this.messagesReceived++;
            
            // 每接收10条消息或收到非心跳消息时记录日志
            if (this.messagesReceived % 10 === 0 || message.type !== SignalingMessageType.PONG) {
              console.log(`SignalingClient[${this.instanceId}]: 已接收消息 #${this.messagesReceived}, 类型: ${message.type}`);
            }
            
            this.handleMessage(message);
          } catch (error) {
            console.error(`SignalingClient[${this.instanceId}]: 解析消息错误:`, error);
          }
        };

        // 连接关闭时
        this.webSocket.onclose = (event) => {
          this.connected = false;
          console.log(`SignalingClient[${this.instanceId}]: 连接已关闭 (代码: ${event.code}): ${event.reason}, 已发送消息: ${this.messagesSent}, 已接收消息: ${this.messagesReceived}`);
          this.handleReconnect();
        };

        // 连接错误时
        this.webSocket.onerror = (error) => {
          console.error(`SignalingClient[${this.instanceId}]: 连接错误:`, error);
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
      console.warn(`SignalingClient[${this.instanceId}]: 收到无效消息格式`);
      return;
    }

    // 如果是PONG消息，更新最后接收PONG的时间
    if (message.type === SignalingMessageType.PONG) {
      this.lastPongTime = Date.now();
      // 每10次心跳响应记录一次日志
      if (this.heartbeatCount % LOG_HEARTBEAT_FREQUENCY === 0) {
        console.log(`SignalingClient[${this.instanceId}]: 收到PONG响应 #${this.heartbeatCount}, WebSocket状态: ${this.webSocket?.readyState}`);
      }
      return;
    }

    // 对于非心跳消息，记录详细日志
    console.log(`SignalingClient[${this.instanceId}]: 处理消息类型: ${message.type}`);

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

      case SignalingMessageType.CONNECTED:
        // 处理服务器确认连接的消息
        console.log(`SignalingClient[${this.instanceId}]: 服务器确认连接已建立`);
        // 可以触发一个连接确认事件
        this.eventEmitter.emit(WebRTCEvent.SIGNALING_CONNECTED, message.payload);
        break;
        
      default:
        console.warn(`SignalingClient[${this.instanceId}]: 未知消息类型:`, message.type);
    }
  }

  /**
   * 发送消息到信令服务器
   * @param message 要发送的消息
   * @returns 是否发送成功
   */
  public send(message: SignalingMessage): boolean {
    if (!this.connected || !this.webSocket) {
      console.error(`SignalingClient[${this.instanceId}]: 无法发送消息，未连接`);
      console.error(`SignalingClient[${this.instanceId}]: 连接URL: ${this.url}, 连接状态: ${this.connected}, WebSocket存在: ${this.webSocket !== null}`);
      return false;
    }

    try {
      this.messagesSent++;
      
      // 仅对非心跳消息或每10条消息记录日志
      if (message.type !== SignalingMessageType.PING || this.messagesSent % 10 === 0) {
        console.log(`SignalingClient[${this.instanceId}]: 发送消息 #${this.messagesSent}, 类型: ${message.type}, WebSocket状态: ${this.webSocket.readyState}`);
      }
      
      this.webSocket.send(JSON.stringify(message));
      return true;
    } catch (error) {
      console.error(`SignalingClient[${this.instanceId}]: 发送消息错误:`, error);
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
      console.error(`SignalingClient[${this.instanceId}]: 达到最大重连尝试次数 (${this.maxReconnectAttempts})`);
      this.eventEmitter.emit(WebRTCEvent.ERROR, new Error('Max reconnect attempts reached'));
      return;
    }

    this.reconnectAttempts++;
    const timeout = this.reconnectTimeout * Math.pow(1.5, this.reconnectAttempts - 1);
    console.log(`SignalingClient[${this.instanceId}]: 将在 ${timeout}ms 后重连 (尝试 ${this.reconnectAttempts}/${this.maxReconnectAttempts})`);

    setTimeout(() => {
      console.log(`SignalingClient[${this.instanceId}]: 开始第 ${this.reconnectAttempts} 次重连尝试`);
      this.connect().catch(error => {
        console.error(`SignalingClient[${this.instanceId}]: 重连失败:`, error);
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
        this.heartbeatCount++;
        
        // 每LOG_HEARTBEAT_FREQUENCY次心跳记录一次日志
        if (this.heartbeatCount % LOG_HEARTBEAT_FREQUENCY === 0) {
          console.log(`SignalingClient[${this.instanceId}]: 发送心跳 #${this.heartbeatCount}, WebSocket状态: ${this.webSocket.readyState}, 已发送消息: ${this.messagesSent}, 已接收消息: ${this.messagesReceived}`);
        }
        
        // 发送ping消息
        this.send({
          type: SignalingMessageType.PING,
          payload: { timestamp: Date.now(), count: this.heartbeatCount }
        });
        
        // 设置超时监测，如果在一定时间内没有收到pong，则认为连接已断开
        this.heartbeatTimeoutTimer = window.setTimeout(() => {
          console.warn(`SignalingClient[${this.instanceId}]: 心跳 #${this.heartbeatCount} 超时，认为连接已断开`);
          this.handleConnectionLost('心跳超时');
        }, HEARTBEAT_TIMEOUT);
      } else {
        console.warn(`SignalingClient[${this.instanceId}]: 无法发送心跳，连接状态: ${this.connected}, WebSocket状态: ${this.webSocket?.readyState}`);
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
    console.error(`SignalingClient[${this.instanceId}]: 连接丢失 (${reason}), 已发送消息: ${this.messagesSent}, 已接收消息: ${this.messagesReceived}, 心跳计数: ${this.heartbeatCount}`);
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
    const wsState = this.webSocket ? this.webSocket.readyState : 'null';
    // 每10次心跳检查一次连接状态并记录日志
    if (this.heartbeatCount % LOG_HEARTBEAT_FREQUENCY === 0) {
      console.log(`SignalingClient[${this.instanceId}]: 连接状态检查 - connected: ${this.connected}, WebSocket状态: ${wsState}, 心跳计数: ${this.heartbeatCount}`);
    }
    return this.connected && this.webSocket?.readyState === WebSocket.OPEN;
  }
}
