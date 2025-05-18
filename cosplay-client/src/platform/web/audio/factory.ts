import { AudioConfig } from '../../../types';
import { AudioFactory, AudioPlayer, AudioRecorder } from '../../types';
import { WebAudioPlayer } from './player';
import { WebAudioRecorder } from './recorder';
import { WebRTCRecorder } from './webrtc-recorder';
import { WebRTCFactory } from '../webrtc';

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
    console.log('WebAudioFactory: Creating recorder with config:', JSON.stringify(config, null, 2));
    console.log('WebAudioFactory: WebRTC supported:', WebRTCFactory.isSupported());
    
    // 如果配置中指定了使用WebRTC，并且环境支持WebRTC，则使用WebRTC录音机
    if (config.useWebRTC === true && WebRTCFactory.isSupported()) {
      console.log('WebAudioFactory: Using WebRTC recorder');
      try {
        const recorder = new WebRTCRecorder(config);
        console.log('WebAudioFactory: WebRTC recorder created successfully');
        return recorder;
      } catch (error) {
        console.error('WebAudioFactory: Error creating WebRTC recorder:', error);
        console.log('WebAudioFactory: Falling back to standard Web Audio recorder');
        return new WebAudioRecorder(config);
      }
    }
    
    // 否则使用传统的Web Audio录音机
    console.log('WebAudioFactory: Using standard Web Audio recorder');
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
  
  /**
   * 检查当前环境是否支持WebRTC
   * @returns 是否支持WebRTC
   */
  public isWebRTCSupported(): boolean {
    return WebRTCFactory.isSupported();
  }
}
