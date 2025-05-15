import { AudioConfig } from '../../../types';
import { AudioFactory, AudioPlayer, AudioRecorder } from '../../types';
import { WebAudioPlayer } from './player';
import { WebAudioRecorder } from './recorder';

/**
 * Web平台音频工厂实现
 */
export class WebAudioFactory implements AudioFactory {
  /**
   * 创建音频录制器
   * @param config 音频配置
   * @returns 音频录制器实例
   */
  public createRecorder(config: AudioConfig): AudioRecorder {
    return new WebAudioRecorder(config);
  }
  
  /**
   * 创建音频播放器
   * @param config 音频配置
   * @returns 音频播放器实例
   */
  public createPlayer(config: AudioConfig): AudioPlayer {
    return new WebAudioPlayer(config);
  }
  
  /**
   * 检查当前环境是否支持音频处理
   * @returns 是否支持
   */
  public isSupported(): boolean {
    // 检查必要的API是否可用
    return !!(window && 
           navigator && 
           navigator.mediaDevices && 
           typeof navigator.mediaDevices.getUserMedia === 'function' && 
           typeof window.AudioContext !== 'undefined');
  }
}
