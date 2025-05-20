# Cosplay Client

一个基于TypeScript的跨平台xiaozhi客户端组件库，用于连接xiaozhi-esp32-server，支持语音交互功能。

## 项目概述

Cosplay Client是一个模块化设计的组件库，旨在提供一套统一的API来与xiaozhi-esp32-server进行通信。本项目采用TypeScript开发，确保类型安全和更好的开发体验。项目架构设计充分考虑了跨平台兼容性，可在Web环境直接使用，并且为后续在React Native中的应用做好了准备。

### 主要特性

- WebSocket稳定连接管理
- Opus音频编解码支持
- 语音采集和播放
- 消息序列化和处理
- 事件驱动的异步通信
- 跨平台友好的抽象设计

## 架构设计

### 分层架构

```
cosplay-client/
├── src/
│   ├── core/                  # 核心平台无关逻辑
│   │   ├── connection/        # 连接管理
│   │   │   ├── websocket.ts   # WebSocket连接实现
│   │   │   └── types.ts       # 连接相关类型定义
│   │   ├── protocol/          # 消息协议
│   │   │   ├── messages.ts    # 消息类型定义
│   │   │   └── handlers.ts    # 消息处理器
│   │   └── events/            # 事件系统
│   ├── platform/              # 平台特定实现
│   │   ├── web/               # Web平台实现
│   │   │   ├── audio/         # Web音频处理
│   │   │   └── storage/       # Web存储实现
│   │   └── types.ts           # 平台接口定义
│   ├── client.ts              # 主客户端类
│   └── index.ts               # 公共API导出
├── demo/                      # React演示应用
│   ├── src/
│   │   ├── components/        # UI组件
│   │   ├── pages/             # 页面组件
│   │   └── App.tsx            # 应用入口
│   └── public/                # 静态资源
├── tests/                     # 测试文件
├── package.json
├── tsconfig.json
└── README.md
```

### 核心模块

1. **连接管理（Connection）**：
   - 管理WebSocket连接生命周期
   - 处理重连逻辑
   - 监控连接状态

2. **音频处理（Audio）**：
   - 音频采集（通过设备麦克风）
   - Opus编解码
   - 音频播放

3. **消息协议（Protocol）**：
   - 消息序列化/反序列化
   - 协议定义和实现
   - 消息处理器

4. **事件系统（Events）**：
   - 基于事件的通信机制
   - 异步事件处理
   - 组件间解耦

## 技术栈

- **语言**：TypeScript
- **构建工具**：Webpack、Rollup
- **测试框架**：Jest
- **演示框架**：React
- **音频处理**：Web Audio API + opus.js (WebAssembly)
- **通信**：WebSocket API

## 跨平台设计

项目采用接口抽象和依赖注入设计模式，将平台特定的实现与业务逻辑分离，为跨平台应用开发奠定基础。

### Web/React实现

在Web环境中，项目直接使用浏览器原生API：
- WebSocket API用于通信
- Web Audio API用于音频处理
- IndexedDB或LocalStorage用于数据持久化

### React Native考虑

为后续React Native适配，项目将：
- 使用平台抽象层隔离平台特定API
- 核心业务逻辑保持平台无关性
- 为关键组件（如音频处理）提供平台特定工厂方法

## 通信协议

### 连接初始化

客户端连接时会发送hello消息，指定支持的音频格式等信息：

```typescript
const helloMessage = {
  type: "hello",
  version: 1,
  transport: "websocket",
  audio_params: {
    format: "opus",
    sample_rate: 16000,
    channels: 1,
    frame_duration: 20,
  }
};
```

### 音频通信

- **客户端到服务器**：
  - 音频数据以二进制格式通过WebSocket发送
  - 支持Opus编码格式，提高传输效率
  - 支持静音检测，减少数据传输

- **服务器到客户端**：
  - 二进制音频数据接收
  - Opus解码
  - 流式播放

### 状态通知

使用JSON消息通知状态变化：

```typescript
const statusMessage = {
  type: "stt",  // speech-to-text
  text: "识别的文本内容",
  final: true,  // 是否为最终结果
  session_id: "xxx"
};
```

## Opus编解码处理

由于在Web环境中原生不支持Opus编解码，项目采用以下策略：

1. **使用WebAssembly实现**：
   - 通过opus.js等库提供WebAssembly实现的Opus编解码
   - 支持实时编码和解码
   - 控制内存使用和性能开销

2. **降级处理**：
   - 对于不支持的环境，可降级使用PCM格式
   - 提供配置选项控制音频质量和带宽使用

## 优先实现功能

第一阶段将优先实现以下功能：

1. **WebSocket连接**：
   - 稳定连接xiaozhi-server
   - 自动重连机制
   - 连接状态监控

2. **Opus音频处理**：
   - 麦克风音频采集
   - Opus编码发送
   - 接收Opus音频并解码播放

3. **基本消息处理**：
   - Hello消息交换
   - 语音转文字结果处理
   - 语音状态管理

## 使用示例

### 基本使用

```typescript
import { CosplayClient } from 'cosplay-client';

// 创建客户端实例
const client = new CosplayClient({
  serverUrl: 'ws://your-server-address/xiaozhi/v1/',
  deviceId: 'web-client-123',
  clientId: 'web-demo'
});

// 设置事件监听
client.on('message', (message) => {
  console.log('收到消息:', message);
});

client.on('speechRecognition', (text, isFinal) => {
  console.log('语音识别结果:', text, isFinal ? '(最终结果)' : '(中间结果)');
});

// 连接服务器
client.connect();

// 开始录音并发送
document.getElementById('startButton').addEventListener('click', () => {
  client.startListening();
});

// 停止录音
document.getElementById('stopButton').addEventListener('click', () => {
  client.stopListening();
});
```

### 在React中使用

```tsx
import React, { useEffect, useState } from 'react';
import { CosplayClient } from 'cosplay-client';

const ChatComponent: React.FC = () => {
  const [client, setClient] = useState<CosplayClient | null>(null);
  const [messages, setMessages] = useState<any[]>([]);
  const [isListening, setIsListening] = useState(false);
  
  useEffect(() => {
    // 初始化客户端
    const cosplayClient = new CosplayClient({
      serverUrl: 'ws://your-server-address/xiaozhi/v1/',
      deviceId: 'web-client-' + Math.random().toString(36).substring(2, 10),
      clientId: 'web-demo'
    });
    
    // 设置事件监听
    cosplayClient.on('speechRecognition', (text, isFinal) => {
      if (isFinal) {
        setMessages(prev => [...prev, { role: 'user', content: text }]);
      }
    });
    
    cosplayClient.on('message', (message) => {
      if (message.type === 'response') {
        setMessages(prev => [...prev, { role: 'assistant', content: message.text }]);
      }
    });
    
    // 连接服务器
    cosplayClient.connect();
    
    setClient(cosplayClient);
    
    // 组件卸载时清理
    return () => {
      cosplayClient.disconnect();
    };
  }, []);
  
  const toggleListening = () => {
    if (!client) return;
    
    if (isListening) {
      client.stopListening();
    } else {
      client.startListening();
    }
    
    setIsListening(!isListening);
  };
  
  return (
    <div className="chat-container">
      <div className="messages">
        {messages.map((msg, index) => (
          <div key={index} className={`message ${msg.role}`}>
            {msg.content}
          </div>
        ))}
      </div>
      
      <button onClick={toggleListening}>
        {isListening ? '停止录音' : '开始录音'}
      </button>
    </div>
  );
};

export default ChatComponent;
```

## 项目开发规划

### 第一阶段：基础设施

- [x] 项目结构设置
- [ ] 核心接口定义
- [ ] WebSocket连接实现
- [ ] 基本音频处理（Web Audio API）
- [ ] Opus编解码集成

### 第二阶段：功能实现

- [ ] 完整消息协议支持
- [ ] 语音活动检测（VAD）
- [ ] 音频流管理
- [ ] 状态管理与事件系统

### 第三阶段：优化与扩展

- [ ] 浏览器兼容性优化
- [ ] 性能优化
- [ ] React Native支持准备
- [ ] 完整演示应用

## 贡献指南

项目遵循模块化设计原则，欢迎贡献新功能或改进。如要贡献，请确保：

1. 遵循现有的代码风格和架构设计
2. 添加适当的测试用例
3. 更新相关文档
4. 提交前运行所有测试

## 环境要求

- Node.js 16+
- npm 7+ 或 yarn 1.22+
- 现代浏览器（Chrome、Firefox、Safari、Edge）支持
  - WebSocket API
  - Web Audio API
  - WebAssembly

## 许可证

[MIT License](LICENSE)
