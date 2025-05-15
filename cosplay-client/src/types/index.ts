/**
 * 客户端配置选项
 */
export interface ClientConfig {
  /** WebSocket服务器URL */
  serverUrl: string;
  /** 设备ID，用于标识客户端 */
  deviceId: string;
  /** 客户端ID，用于标识客户端类型 */
  clientId: string;
  /** 音频配置选项 */
  audioConfig?: AudioConfig;
  /** 自动重连选项 */
  reconnect?: ReconnectOptions;
}

/**
 * 音频配置选项
 */
export interface AudioConfig {
  /** 音频格式，默认为opus */
  format?: 'opus' | 'pcm';
  /** 采样率，默认为16000 */
  sampleRate?: number;
  /** 声道数，默认为1 */
  channels?: number;
  /** 帧长度（毫秒），默认为20 */
  frameDuration?: number;
}

/**
 * 重连配置选项
 */
export interface ReconnectOptions {
  /** 是否启用自动重连，默认为true */
  enabled?: boolean;
  /** 最大重连次数，默认为10 */
  maxAttempts?: number;
  /** 重连延迟（毫秒），默认为1000 */
  delay?: number;
  /** 重连延迟的最大值（毫秒），默认为30000 */
  maxDelay?: number;
  /** 重连延迟增长因子，默认为1.5 */
  factor?: number;
}

/**
 * 消息类型
 */
export enum MessageType {
  HELLO = 'hello',
  AUDIO = 'audio',
  TEXT = 'text',
  STT = 'stt',
  TTS = 'tts',
  ABORT = 'abort',
  LISTEN = 'listen',
  ERROR = 'error'
}

/**
 * 客户端事件类型
 */
export enum ClientEvent {
  CONNECTING = 'connecting',
  CONNECTED = 'connected',
  DISCONNECTED = 'disconnected',
  MESSAGE = 'message',
  ERROR = 'error',
  SPEECH_START = 'speechStart',
  SPEECH_END = 'speechEnd',
  SPEECH_RECOGNITION = 'speechRecognition',
  AUDIO_PLAY_START = 'audioPlayStart',
  AUDIO_PLAY_END = 'audioPlayEnd'
}

/**
 * 连接状态
 */
export enum ConnectionState {
  DISCONNECTED = 'disconnected',
  CONNECTING = 'connecting',
  CONNECTED = 'connected',
  RECONNECTING = 'reconnecting',
  ERROR = 'error'
}

/**
 * 语音状态
 */
export enum ListeningState {
  IDLE = 'idle',
  LISTENING = 'listening',
  PROCESSING = 'processing'
}

/**
 * Hello消息接口
 */
export interface HelloMessage {
  type: MessageType.HELLO;
  version: number;
  transport: string;
  session_id?: string;
  audio_params: {
    format: string;
    sample_rate: number;
    channels: number;
    frame_duration: number;
  };
}

/**
 * STT（语音转文字）消息接口
 */
export interface SttMessage {
  type: MessageType.STT;
  text: string;
  final: boolean;
  session_id: string;
}

/**
 * TTS（文字转语音）状态消息接口
 */
export interface TtsStatusMessage {
  type: MessageType.TTS;
  state: 'sentence_start' | 'sentence_end' | 'stop';
  text?: string;
  session_id: string;
}

/**
 * 通用消息接口
 */
export type Message = HelloMessage | SttMessage | TtsStatusMessage | Record<string, any>;
