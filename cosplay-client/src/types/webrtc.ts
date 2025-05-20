/**
 * WebRTC相关类型定义
 */

/**
 * WebRTC配置
 */
export interface WebRTCConfig {
  // ICE服务器配置
  iceServers: RTCIceServer[];
  // ICE传输策略
  iceTransportPolicy?: RTCIceTransportPolicy;
  // 媒体约束
  mediaConstraints: MediaStreamConstraints;
  // 是否启用回声消除
  echoCancellation?: boolean;
  // 是否启用噪声抑制
  noiseSuppression?: boolean;
  // 是否启用自动增益控制
  autoGainControl?: boolean;
  // 采样率
  sampleRate?: number;
  // 信令服务器URL
  signalingUrl: string;
}

/**
 * WebRTC连接事件类型
 */
export enum WebRTCEvent {
  // WebRTC连接已建立
  CONNECTED = 'webrtc:connected',
  // WebRTC连接已关闭
  DISCONNECTED = 'webrtc:disconnected',
  // 接收到远程音频
  AUDIO_RECEIVED = 'webrtc:audio_received',
  // 本地音频发送
  AUDIO_SENT = 'webrtc:audio_sent',
  // 连接发生错误
  ERROR = 'webrtc:error',
  // 信令服务器连接已建立
  SIGNALING_CONNECTED = 'signaling:connected',
  // 信令服务器连接已关闭
  SIGNALING_DISCONNECTED = 'signaling:disconnected',
}

/**
 * WebRTC连接状态
 */
export enum WebRTCConnectionState {
  NEW = 'new',
  CONNECTING = 'connecting',
  CONNECTED = 'connected',
  DISCONNECTED = 'disconnected',
  FAILED = 'failed',
  CLOSED = 'closed',
}

/**
 * 信令消息类型
 */
export enum SignalingMessageType {
  OFFER = 'offer',
  ANSWER = 'answer',
  ICE_CANDIDATE = 'ice-candidate',
  PING = 'ping',
  PONG = 'pong',
  CONNECTED = 'connected',
}

/**
 * 信令消息接口
 */
export interface SignalingMessage {
  type: SignalingMessageType;
  payload?: any;
}
