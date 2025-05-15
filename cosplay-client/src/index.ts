// 导出核心客户端类
export { CosplayClient } from './client';

// 导出类型定义
export {
  AudioConfig,
  ClientConfig,
  ClientEvent,
  ConnectionState,
  ListeningState,
  MessageType,
  Message,
  HelloMessage,
  SttMessage,
  TtsStatusMessage
} from './types';

// 导出接口定义，便于扩展
export { Connection, ConnectionFactory } from './core/connection/types';
export { AudioRecorder, AudioPlayer, AudioFactory } from './platform/types';

// 导出默认实现
export { WebSocketConnection } from './core/connection/websocket';
export { DefaultConnectionFactory } from './core/connection/factory';
export { WebAudioFactory } from './platform/web/audio/factory';
export { WebAudioRecorder } from './platform/web/audio/recorder';
export { WebAudioPlayer } from './platform/web/audio/player';
