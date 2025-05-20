// 为cosplay-client添加类型扩展

import 'cosplay-client';

declare module 'cosplay-client' {
  interface AudioConfig {
    /** 是否使用WebRTC，默认为false */
    useWebRTC?: boolean;
    /** WebRTC信令服务器URL */
    webrtcSignalingUrl?: string;
    /** 是否启用回声消除，默认为true */
    echoCancellation?: boolean;
    /** 是否启用噪声抑制，默认为true */
    noiseSuppression?: boolean;
    /** 是否启用自动增益控制，默认为true */
    autoGainControl?: boolean;
  }
}
