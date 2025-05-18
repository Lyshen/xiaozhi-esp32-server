# WebRTC音频模块

本模块为xiaozhi-server提供WebRTC功能支持，实现基于WebRTC的实时音频处理，替代原有的Opus处理管道。

## 功能特点

- 点对点音频传输，减少延迟
- 支持配置多个STUN/TURN服务器
- 与现有音频处理逻辑无缝集成
- 可通过配置文件控制启用/禁用
- 支持回退到原有Opus处理

## 配置说明

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

完整配置示例见`data/webrtc_config_sample.yaml`。

## 使用流程

1. 在配置文件中启用WebRTC功能
2. 启动服务器
3. 客户端通过WebRTC信令端点（默认`ws://<server-ip>:8082/ws/signaling`）建立连接
4. 完成WebRTC握手后，音频数据将通过WebRTC通道传输

## 依赖项

- aiortc: Python的WebRTC实现
- av: 音频/视频处理库
- aioice: ICE协议支持

## 信令协议

### 建立连接

1. 客户端连接到信令WebSocket
2. 服务器返回连接确认消息，包含`client_id`和`session_id`
3. 客户端发送offer
4. 服务器响应answer
5. 双方交换ICE候选

### 消息格式

```json
// 客户端offer
{
  "type": "offer",
  "sdp": "..."
}

// 服务器answer
{
  "type": "answer",
  "sdp": "..."
}

// ICE候选
{
  "type": "ice-candidate",
  "candidate": "..."
}
```

## 调试与排查

如果WebRTC连接有问题，请检查：

1. 配置文件中的STUN/TURN服务器是否可用
2. 客户端和服务器之间的网络连接（防火墙、NAT等）
3. 服务器日志中的WebRTC相关信息
