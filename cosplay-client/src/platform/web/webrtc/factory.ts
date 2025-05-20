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
    console.log('[DEBUG] WebRTCFactory.createAudioConnection called');
    console.log('[DEBUG] WebRTC config:', JSON.stringify({
      signalingUrl: config.signalingUrl,
      sampleRate: config.sampleRate,
      echoCancellation: config.echoCancellation,
      noiseSuppression: config.noiseSuppression,
      autoGainControl: config.autoGainControl
    }, null, 2));
    
    if (!WebRTCFactory.isSupported()) {
      console.error('[DEBUG] WebRTC is not supported in this environment');
      throw new Error('WebRTC is not supported in the current environment');
    }

    // 如果已经有实例，直接返回现有实例
    if (WebRTCFactory.audioConnectionInstance) {
      console.log('[DEBUG] WebRTCFactory: Reusing existing WebRTC audio connection instance');
      console.log('[DEBUG] Instance ID:', WebRTCFactory.audioConnectionInstance.getInstanceId());
      return WebRTCFactory.audioConnectionInstance;
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

    console.log('[DEBUG] Creating new WebRTC audio connection with final config:', JSON.stringify({
      signalingUrl: finalConfig.signalingUrl,
      sampleRate: finalConfig.sampleRate,
      echoCancellation: finalConfig.echoCancellation,
      noiseSuppression: finalConfig.noiseSuppression,
      autoGainControl: finalConfig.autoGainControl
    }, null, 2));

    // 创建新实例并存储
    WebRTCFactory.audioConnectionInstance = new WebRTCAudioConnection(finalConfig);
    console.log('[DEBUG] WebRTCFactory: Created new WebRTC audio connection instance');
    console.log('[DEBUG] New instance ID:', WebRTCFactory.audioConnectionInstance.getInstanceId());
    return WebRTCFactory.audioConnectionInstance;
  }
}
