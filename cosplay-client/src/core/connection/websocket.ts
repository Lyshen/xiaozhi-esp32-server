import { ClientConfig, ConnectionState } from '../../types';
import { Connection } from './types';

/**
 * WebSocket连接实现类
 */
export class WebSocketConnection implements Connection {
  private ws: WebSocket | null = null;
  private state: ConnectionState = ConnectionState.DISCONNECTED;
  private config: ClientConfig;
  private reconnectAttempts: number = 0;
  private reconnectTimeout: any = null;
  private messageHandler: ((data: string | ArrayBuffer) => void) | null = null;
  private errorHandler: ((error: Error) => void) | null = null;
  private stateChangeHandler: ((state: ConnectionState) => void) | null = null;

  /**
   * 构造函数
   * @param config 客户端配置
   */
  constructor(config: ClientConfig) {
    this.config = config;
  }

  /**
   * 建立WebSocket连接
   * @returns 连接是否成功的Promise
   */
  public async connect(): Promise<boolean> {
    if (this.state === ConnectionState.CONNECTING || this.state === ConnectionState.CONNECTED) {
      return this.state === ConnectionState.CONNECTED;
    }

    this.updateState(ConnectionState.CONNECTING);

    try {
      return await this.createWebSocketConnection();
    } catch (error) {
      this.handleError(error as Error);
      return false;
    }
  }

  /**
   * 断开WebSocket连接
   */
  public disconnect(): void {
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }

    if (this.ws) {
      // 移除所有事件监听器
      this.ws.onopen = null;
      this.ws.onclose = null;
      this.ws.onerror = null;
      this.ws.onmessage = null;

      // 如果连接已经打开，正常关闭它
      if (this.ws.readyState === WebSocket.OPEN) {
        this.ws.close();
      }

      this.ws = null;
    }

    this.updateState(ConnectionState.DISCONNECTED);
    this.reconnectAttempts = 0;
  }

  /**
   * 发送文本消息
   * @param message 要发送的文本消息
   */
  public async sendText(message: string): Promise<void> {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      throw new Error('WebSocket not connected');
    }

    this.ws.send(message);
  }

  /**
   * 发送二进制数据
   * @param data 要发送的二进制数据
   */
  public async sendBinary(data: ArrayBuffer): Promise<void> {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      throw new Error('WebSocket not connected');
    }

    this.ws.send(data);
  }

  /**
   * 获取当前连接状态
   */
  public getState(): ConnectionState {
    return this.state;
  }

  /**
   * 设置消息处理器
   * @param handler 消息处理函数
   */
  public setMessageHandler(handler: (data: string | ArrayBuffer) => void): void {
    this.messageHandler = handler;
  }

  /**
   * 设置错误处理器
   * @param handler 错误处理函数
   */
  public setErrorHandler(handler: (error: Error) => void): void {
    this.errorHandler = handler;
  }

  /**
   * 设置状态变化处理器
   * @param handler 状态变化处理函数
   */
  public setStateChangeHandler(handler: (state: ConnectionState) => void): void {
    this.stateChangeHandler = handler;
  }

  /**
   * 创建WebSocket连接
   * @returns 连接是否成功的Promise
   */
  private createWebSocketConnection(): Promise<boolean> {
    return new Promise((resolve, reject) => {
      try {
        // 构建包含设备ID和客户端ID的WebSocket URL
        let url = this.config.serverUrl;
        const hasParams = url.includes('?');
        const separator = hasParams ? '&' : '?';
        
        // 添加device-id参数
        if (this.config.deviceId) {
          url += `${separator}device-id=${encodeURIComponent(this.config.deviceId)}`;
        }
        
        // 添加client-id参数
        if (this.config.clientId) {
          url += `${url.includes('?') ? '&' : '?'}client-id=${encodeURIComponent(this.config.clientId)}`;
        }
        
        this.ws = new WebSocket(url);

        this.ws.onopen = () => {
          this.onConnectionOpen();
          resolve(true);
        };

        this.ws.onclose = (event) => {
          this.onConnectionClose(event);
          if (this.state !== ConnectionState.DISCONNECTED) {
            resolve(false);
          }
        };

        this.ws.onerror = (event) => {
          this.onConnectionError(event);
          reject(new Error('WebSocket connection error'));
        };

        this.ws.onmessage = (event) => {
          this.onMessage(event);
        };
      } catch (error) {
        this.updateState(ConnectionState.ERROR);
        reject(error);
      }
    });
  }

  /**
   * WebSocket连接打开时的处理
   */
  private onConnectionOpen(): void {
    this.updateState(ConnectionState.CONNECTED);
    this.reconnectAttempts = 0;
  }

  /**
   * WebSocket连接关闭时的处理
   */
  private onConnectionClose(event: CloseEvent): void {
    if (this.state === ConnectionState.DISCONNECTED) {
      return;
    }

    const shouldReconnect = this.shouldAttemptReconnect();
    this.updateState(shouldReconnect ? ConnectionState.RECONNECTING : ConnectionState.DISCONNECTED);

    if (shouldReconnect) {
      this.scheduleReconnect();
    }
  }

  /**
   * WebSocket连接出错时的处理
   */
  private onConnectionError(event: Event): void {
    this.handleError(new Error('WebSocket error'));
  }

  /**
   * 接收到消息时的处理
   */
  private onMessage(event: MessageEvent): void {
    if (this.messageHandler) {
      this.messageHandler(event.data);
    }
  }

  /**
   * 更新连接状态
   */
  private updateState(newState: ConnectionState): void {
    if (this.state === newState) {
      return;
    }

    this.state = newState;

    if (this.stateChangeHandler) {
      this.stateChangeHandler(newState);
    }
  }

  /**
   * 处理错误
   */
  private handleError(error: Error): void {
    this.updateState(ConnectionState.ERROR);
    
    if (this.errorHandler) {
      this.errorHandler(error);
    }
  }

  /**
   * a判断是否应该尝试重连
   */
  private shouldAttemptReconnect(): boolean {
    const reconnectConfig = this.config.reconnect || {};
    const enabled = reconnectConfig.enabled !== false;
    const maxAttempts = reconnectConfig.maxAttempts || 10;

    return enabled && this.reconnectAttempts < maxAttempts;
  }

  /**
   * 安排重连
   */
  private scheduleReconnect(): void {
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
    }

    const reconnectConfig = this.config.reconnect || {};
    const initialDelay = reconnectConfig.delay || 1000;
    const maxDelay = reconnectConfig.maxDelay || 30000;
    const factor = reconnectConfig.factor || 1.5;

    // 计算退避延迟
    const delay = Math.min(initialDelay * Math.pow(factor, this.reconnectAttempts), maxDelay);

    this.reconnectTimeout = setTimeout(() => {
      this.reconnectAttempts++;
      this.reconnectTimeout = null;
      this.connect().catch(() => {
        // 连接失败，由onConnectionClose处理重连
      });
    }, delay);
  }
}
