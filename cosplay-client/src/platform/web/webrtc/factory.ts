import { WebRTCAudioConnection } from './audio-connection';
import { WebRTCConfig } from '../../../types/webrtc';

/**
 * WebRTC工厂类
 * 负责创建WebRTC相关组件
 */
export class WebRTCFactory {
  // 实现单例模式，确保只创建一个WebRTC连接实例
  private static audioConnectionInstance: WebRTCAudioConnection | null = null;
  
  /**
   * 检查当前环境是否支持WebRTC
   * @returns 是否支持WebRTC
   */
  public static isSupported(): boolean {
    return (
      typeof window !== 'undefined' &&
      !!window.RTCPeerConnection &&
      !!navigator.mediaDevices &&
      !!navigator.mediaDevices.getUserMedia
    );
  }

  /**
   * 创建WebRTC音频连接
   * @param config WebRTC配置
   * @returns WebRTC音频连接实例
   */
  public static createAudioConnection(config: WebRTCConfig): WebRTCAudioConnection {
    // 检查WebRTC支持
    if (!WebRTCFactory.isSupported()) {
      throw new Error('WebRTC is not supported in the current environment');
    }

    // 如果已经有实例，直接返回现有实例
    if (WebRTCFactory.audioConnectionInstance) {
      return WebRTCFactory.audioConnectionInstance;
    }

    // 设置默认配置
    const finalConfig: WebRTCConfig = {
      iceServers: config.iceServers || [
        { urls: 'stun:stun.l.google.com:19302' }
      ],
      iceTransportPolicy: config.iceTransportPolicy || 'all',
      mediaConstraints: config.mediaConstraints || {
        audio: {
          echoCancellation: config.echoCancellation !== false,
          noiseSuppression: config.noiseSuppression !== false,
          autoGainControl: config.autoGainControl !== false
        },
        video: false
      },
      echoCancellation: config.echoCancellation !== false,
      noiseSuppression: config.noiseSuppression !== false,
      autoGainControl: config.autoGainControl !== false,
      sampleRate: config.sampleRate || 16000,
      signalingUrl: config.signalingUrl || 'wss://xiaozhi.qiniu.io/ws/signaling'
    };

    // 创建新实例并存储
    WebRTCFactory.audioConnectionInstance = new WebRTCAudioConnection(finalConfig);
    return WebRTCFactory.audioConnectionInstance;
  }
}
