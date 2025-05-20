import { ClientConfig, ConnectionState } from '../../types';

/**
 * WebSocket连接接口，定义连接管理的基本操作
 */
export interface Connection {
  /**
   * 建立连接
   * @returns 连接是否成功的Promise
   */
  connect(): Promise<boolean>;
  
  /**
   * 断开连接
   */
  disconnect(): void;
  
  /**
   * 发送文本消息
   * @param message 要发送的文本消息
   */
  sendText(message: string): Promise<void>;
  
  /**
   * 发送二进制数据
   * @param data 要发送的二进制数据
   */
  sendBinary(data: ArrayBuffer): Promise<void>;
  
  /**
   * 获取当前连接状态
   */
  getState(): ConnectionState;
  
  /**
   * 设置消息处理器
   * @param handler 消息处理函数
   */
  setMessageHandler(handler: (data: string | ArrayBuffer) => void): void;
  
  /**
   * 设置错误处理器
   * @param handler 错误处理函数
   */
  setErrorHandler(handler: (error: Error) => void): void;
  
  /**
   * 设置状态变化处理器
   * @param handler 状态变化处理函数
   */
  setStateChangeHandler(handler: (state: ConnectionState) => void): void;
}

/**
 * 连接工厂接口，负责创建适合当前环境的连接实例
 */
export interface ConnectionFactory {
  /**
   * 创建连接实例
   * @param config 客户端配置
   */
  createConnection(config: ClientConfig): Connection;
}
