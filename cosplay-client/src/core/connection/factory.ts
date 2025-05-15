import { ClientConfig } from '../../types';
import { Connection, ConnectionFactory } from './types';
import { WebSocketConnection } from './websocket';

/**
 * 默认连接工厂实现，用于创建WebSocket连接
 */
export class DefaultConnectionFactory implements ConnectionFactory {
  /**
   * 创建适合当前环境的连接实例
   * @param config 客户端配置
   * @returns 连接实例
   */
  createConnection(config: ClientConfig): Connection {
    return new WebSocketConnection(config);
  }
}
