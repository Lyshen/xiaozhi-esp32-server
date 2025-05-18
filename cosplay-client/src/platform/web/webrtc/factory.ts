import { WebRTCAudioConnection } from './audio-connection';
import { WebRTCConfig } from '../../../types/webrtc';

/**
 * WebRTC工厂类
 * 负责创建WebRTC相关组件
 */
export class WebRTCFactory {
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
    if (!WebRTCFactory.isSupported()) {
      throw new Error('WebRTC is not supported in the current environment');
    }

    // 设置默认配置
    const finalConfig: WebRTCConfig = {
      // 默认STUN服务器
      iceServers: config.iceServers || [
        { urls: 'stun:stun.l.google.com:19302' },
        { urls: 'stun:stun1.l.google.com:19302' }
      ],
      iceTransportPolicy: config.iceTransportPolicy || 'all',
      // 默认媒体约束
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

    return new WebRTCAudioConnection(finalConfig);
  }
}
