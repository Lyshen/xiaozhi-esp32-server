import { WebSocketConnection } from '../../src/core/connection/websocket';
import { ConnectionState, ClientEvent } from '../../src/types';

// 创建一个WebSocket的模拟实现
class MockWebSocket {
  url: string;
  onopen: ((event: any) => void) | null = null;
  onclose: ((event: any) => void) | null = null;
  onmessage: ((event: any) => void) | null = null;
  onerror: ((event: any) => void) | null = null;
  readyState: number = 0; // WebSocket.CONNECTING
  
  constructor(url: string) {
    this.url = url;
    // 模拟连接过程，100ms后连接成功
    setTimeout(() => {
      this.readyState = 1; // WebSocket.OPEN
      if (this.onopen) this.onopen({});
    }, 100);
  }
  
  send(data: string | ArrayBuffer): void {
    // 模拟发送逻辑
  }
  
  close(): void {
    // 模拟关闭逻辑
    this.readyState = 3; // WebSocket.CLOSED
    if (this.onclose) this.onclose({ code: 1000, reason: 'Normal closure', wasClean: true });
  }
  
  // 辅助方法：模拟接收消息
  mockReceiveMessage(data: any): void {
    if (this.onmessage) {
      this.onmessage({ data });
    }
  }
  
  // 辅助方法：模拟发生错误
  mockError(error: any): void {
    if (this.onerror) {
      this.onerror({ error });
    }
  }
}

// 用我们的Mock替换全局WebSocket
(global as any).WebSocket = MockWebSocket;

describe('WebSocketConnection', () => {
  let connection: WebSocketConnection;
  const serverUrl = 'ws://localhost:8080/ws';
  
  beforeEach(() => {
    // 创建一个新连接实例
    connection = new WebSocketConnection({
      serverUrl,
      deviceId: 'test-device',
      clientId: 'test-client',
      reconnect: {
        enabled: true,
        maxAttempts: 3
      }
    });
  });
  
  afterEach(() => {
    // 断开连接
    connection.disconnect();
  });
  
  test('should initialize in disconnected state', () => {
    expect(connection.getState()).toBe(ConnectionState.DISCONNECTED);
  });
  
  test('should change state to connecting when connect is called', () => {
    connection.connect();
    expect(connection.getState()).toBe(ConnectionState.CONNECTING);
  });
  
  test('should change state to connected after successful connection', (done) => {
    // 使用setStateChangeHandler注册状态变化监听器
    connection.setStateChangeHandler((state) => {
      if (state === ConnectionState.CONNECTED) {
        expect(connection.getState()).toBe(ConnectionState.CONNECTED);
        done();
      }
    });
    
    connection.connect();
  });
  
  test('should emit message event when receiving a message', (done) => {
    const testMessage = JSON.stringify({ type: 'test', data: 'Hello, World!' });
    
    // 注册消息处理器
    connection.setMessageHandler((message) => {
      expect(message).toBe(testMessage);
      done();
    });
    
    // 注册状态变化处理器
    connection.setStateChangeHandler((state) => {
      if (state === ConnectionState.CONNECTED) {
        // 连接成功后，模拟接收消息
        (connection as any).ws.mockReceiveMessage(testMessage);
      }
    });
    
    connection.connect();
  });
  
  test('should send messages successfully when connected', (done) => {
    const testMessage = { type: 'test', data: 'Hello, Server!' };
    
    // 临时替代发送方法来验证是否发送了正确的数据
    const originalSend = MockWebSocket.prototype.send;
    MockWebSocket.prototype.send = function(data) {
      expect(data).toBe(JSON.stringify(testMessage));
      done();
      return originalSend.call(this, data);
    };
    
    connection.setStateChangeHandler((state) => {
      if (state === ConnectionState.CONNECTED) {
        // 连接成功后发送消息
        connection.sendText(JSON.stringify(testMessage));
      }
    });
    
    connection.connect();
    
    // 测试完成后恢复原始方法
    afterAll(() => {
      MockWebSocket.prototype.send = originalSend;
    });
  });
  
  test('should handle disconnection', (done) => {
    connection.setStateChangeHandler((state) => {
      if (state === ConnectionState.CONNECTED) {
        // 连接成功后断开连接
        connection.disconnect();
      } else if (state === ConnectionState.DISCONNECTED) {
        expect(connection.getState()).toBe(ConnectionState.DISCONNECTED);
        done();
      }
    });
    
    connection.connect();
  });
});
