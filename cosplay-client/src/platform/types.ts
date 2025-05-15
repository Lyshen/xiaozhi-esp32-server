import { AudioConfig } from '../types';

/**
 * 音频录制接口，定义音频采集的基本操作
 */
export interface AudioRecorder {
  /**
   * 开始录音
   * @returns 是否成功开始录音的Promise
   */
  start(): Promise<boolean>;
  
  /**
   * 停止录音
   */
  stop(): void;
  
  /**
   * 暂停录音
   */
  pause(): void;
  
  /**
   * 恢复录音
   */
  resume(): void;
  
  /**
   * 检查是否正在录音
   */
  isRecording(): boolean;
  
  /**
   * 设置音频数据回调
   * @param callback 回调函数，接收音频数据
   */
  setAudioCallback(callback: (data: ArrayBuffer) => void): void;
}

/**
 * 音频播放接口，定义音频播放的基本操作
 */
export interface AudioPlayer {
  /**
   * 播放音频数据
   * @param data 音频数据
   * @returns 是否成功开始播放的Promise
   */
  play(data: ArrayBuffer): Promise<boolean>;
  
  /**
   * 停止播放
   */
  stop(): void;
  
  /**
   * 暂停播放
   */
  pause(): void;
  
  /**
   * 恢复播放
   */
  resume(): void;
  
  /**
   * 检查是否正在播放
   */
  isPlaying(): boolean;
  
  /**
   * 设置播放完成回调
   * @param callback 回调函数，播放完成时调用
   */
  setPlaybackEndCallback(callback: () => void): void;
}

/**
 * 音频工厂接口，负责创建适合当前环境的音频录制和播放实例
 */
export interface AudioFactory {
  /**
   * 创建音频录制器
   * @param config 音频配置
   */
  createRecorder(config: AudioConfig): AudioRecorder;
  
  /**
   * 创建音频播放器
   * @param config 音频配置
   */
  createPlayer(config: AudioConfig): AudioPlayer;
  
  /**
   * 检查当前环境是否支持音频处理
   */
  isSupported(): boolean;
}
