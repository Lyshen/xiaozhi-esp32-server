# WebRTC音频通信接口文档

本文档详细说明了小智WebRTC模块的客户端和服务端接口定义，以确保正确集成和使用基于WebRTC的实时音频通信功能。

## 系统架构

### 服务端组件
- **信令服务器**：处理WebRTC连接建立所需的信令交换
- **连接管理器**：管理WebRTC对等连接的创建、维护和关闭
- **媒体处理器**：处理收到的音频轨道和数据

### 客户端组件
- **信令客户端**：与服务端信令服务器通信
- **音频连接**：管理WebRTC连接和媒体处理
- **录音器**：处理音频采集和传输

## WebRTC信令协议

### 连接建立流程

1. **初始连接**
   - 客户端连接到信令WebSocket: `ws://<server-ip>:<port>/ws/signaling`
   - 服务端返回连接确认消息: `{"type": "connected", "client_id": "UUID"}`

2. **会话建立**
   - 客户端创建并发送Offer
   - 服务端接收Offer，创建并发送Answer
   - 客户端和服务端交换ICE候选者

3. **媒体流处理**
   - 一旦连接建立，音频数据通过WebRTC P2P通道直接传输

### 消息格式规范

#### 1. 客户端发送Offer
```json
{
  "type": "offer",
  "payload": {
    "type": "offer",
    "sdp": "v=0\r\no=- 1234567890 1 IN IP4 127.0.0.1\r\n..."
  }
}
```

#### 2. 服务端发送Answer
```json
{
  "type": "answer",
  "payload": {
    "type": "answer",
    "sdp": "v=0\r\no=- 9876543210 1 IN IP4 0.0.0.0\r\n..."
  }
}
```

#### 3. 客户端发送ICE候选者
```json
{
  "type": "ice_candidate",
  "payload": {
    "candidate": "candidate:1 1 UDP 2113937151 192.168.1.1 56789 typ host",
    "sdpMid": "0",
    "sdpMLineIndex": 0
  }
}
```

#### 4. 服务端发送ICE候选者
```json
{
  "type": "ice_candidate",
  "payload": {
    "candidate": "candidate:1 1 UDP 2113937151 192.168.1.2 56789 typ host",
    "sdpMid": "0",
    "sdpMLineIndex": 0
  }
}
```

## 客户端接口定义

### 1. 信令客户端 (SignalingClient)

```typescript
class SignalingClient {
  // 连接到信令服务器
  connect(url: string): Promise<void>;
  
  // 发送Offer
  sendOffer(offer: RTCSessionDescriptionInit): void;
  
  // 发送ICE候选
  sendIceCandidate(candidate: RTCIceCandidate | null): void;
  
  // 事件监听器
  on(event: 'connected' | 'answer' | 'ice_candidate' | 'error', callback: Function): void;
  
  // 关闭连接
  close(): void;
}
```

### 2. 音频连接 (WebRTCAudioConnection)

```typescript
class WebRTCAudioConnection {
  // 初始化连接
  initialize(config: WebRTCConfig): Promise<void>;
  
  // 开始连接过程
  connect(): Promise<void>;
  
  // 处理远程Answer
  handleRemoteAnswer(answer: any): Promise<void>;
  
  // 处理远程ICE候选
  handleRemoteIceCandidate(candidate: any): void;
  
  // 关闭连接
  close(): void;
}
```

## 服务端接口定义

### 1. 信令服务 (SignalingServer)

```python
class SignalingServer:
    # 初始化信令服务
    async def initialize(self, app, path, connection_manager):
        pass
        
    # 处理新连接
    async def handle_connection(self, ws):
        pass
        
    # 处理文本消息
    async def handle_text_message(self, client_id, ws, data):
        pass
        
    # 关闭连接
    async def close_connection(self, client_id):
        pass
```

### 2. 连接管理器 (ConnectionManager)

```python
class ConnectionManager:
    # 初始化连接管理器
    def __init__(self, config):
        pass
        
    # 创建对等连接
    async def create_peer_connection(self, client_id):
        pass
        
    # 处理Offer
    async def handle_offer(self, client_id, offer_data, websocket=None):
        pass
        
    # 处理ICE候选
    async def handle_ice_candidate(self, client_id, candidate_data):
        pass
        
    # 关闭连接
    async def close_connection(self, client_id):
        pass
```

## 配置说明

### 服务端配置

在`data/.config.yaml`中添加以下配置启用WebRTC功能：

```yaml
webrtc:
  # 是否启用WebRTC功能
  enabled: true
  
  # WebRTC信令WebSocket路径
  signaling_path: "/ws/signaling"
  
  # WebRTC服务端口（默认8082）
  port: 8082
  
  # 是否用WebRTC替换原有Opus处理
  replace_opus: true
  
  # STUN服务器配置（推荐使用国内STUN服务器）
  stun_servers:
    - urls: "stun:stun.chat.bilibili.com:3478"
    - urls: "stun:stun.miwifi.com:3478"
```

### 客户端配置

```javascript
const webrtcConfig = {
  format: "pcm",
  sampleRate: 16000,
  channels: 1,
  frameDuration: 20,
  useWebRTC: true,
  webrtcSignalingUrl: "ws://server-ip:8082/ws/signaling",
  echoCancellation: true,
  noiseSuppression: true,
  autoGainControl: true
};
```

## 常见问题排查

### 连接问题

1. **ICE连接失败**：
   - 检查STUN/TURN服务器配置
   - 确认网络环境允许UDP通信
   - 检查客户端和服务端的防火墙设置

2. **信令交换问题**：
   - 验证信令消息格式是否符合规范
   - 检查客户端和服务端的信令URL是否匹配
   - 确认WebSocket连接已成功建立

3. **媒体流问题**：
   - 确认浏览器已授权访问麦克风
   - 检查音频格式和编码设置是否匹配
   - 调整音频处理参数（降噪、回声消除等）

### 诊断工具

- 使用浏览器的WebRTC调试工具（如Chrome的`chrome://webrtc-internals/`）
- 分析服务端日志中的WebRTC相关信息
- 使用网络分析工具检查ICE候选者和媒体流
