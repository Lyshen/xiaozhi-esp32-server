/**
 * 类型声明文件，用于opus-recorder库
 */
declare module 'opus-recorder' {
  /**
   * Opus录音机配置选项
   */
  interface OpusRecorderOptions {
    /** 编码器Worker的路径 */
    encoderPath?: string;
    /** 编码器采样率 */
    encoderSampleRate?: number;
    /** 编码器应用（音频/语音） */
    encoderApplication?: number;
    /** 帧大小（毫秒） */
    encoderFrameSize?: number;
    /** 比特率 */
    encoderBitRate?: number;
    /** 通道数 */
    numberOfChannels?: number;
    /** 最大缓冲区（每个通道采样数） */
    maxBuffersPerPage?: number;
    /** 是否立即输出编码数据（可流式传输） */
    streamPages?: boolean;
    /** 监听增益 */
    monitorGain?: number;
    /** 录制增益 */
    recordingGain?: number;
    /** 原始采样率重写 */
    originalSampleRateOverride?: number;
    /** 编码复杂度 */
    encoderComplexity?: number;
  }

  /**
   * Opus录音机类
   */
  class Recorder {
    /**
     * 构造函数
     * @param options 录音机配置选项
     */
    constructor(options?: OpusRecorderOptions);

    /**
     * 开始录制
     * @param stream 可选的媒体流
     */
    start(stream?: MediaStream): void;

    /**
     * 暂停录制
     */
    pause(): void;

    /**
     * 恢复录制
     */
    resume(): void;
    
    /**
     * 停止录制
     */
    stop(): void;
    
    /**
     * 关闭录音机并释放资源
     */
    close(): void;
    
    /**
     * 清除录制的音频
     */
    clearStream(): void;
    
    /**
     * 初始化worker
     */
    initWorker(): void;
    
    /**
     * 记录音频数据
     * @param buffer 音频数据
     */
    record(buffer: Float32Array): void;

    /**
     * 当数据可用时触发的回调
     */
    ondataavailable: (arrayBuffer: ArrayBuffer) => void;
    
    /**
     * 当录音机准备就绪时触发的回调
     */
    onready: () => void;
    
    /**
     * 当录音机发生错误时触发的回调
     */
    onError: (error: any) => void;
  }

  export default Recorder;
}
