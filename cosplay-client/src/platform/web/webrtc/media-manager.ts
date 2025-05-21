import { EventEmitter } from 'events';
import { WebRTCEvent } from '../../../types/webrtc';

/**
 * WebRTC媒体管理器
 * 负责管理媒体流的获取、处理和释放
 * 使用标准WebRTC MediaStream API传输音频数据
 */
export class MediaManager {
  private localStream: MediaStream | null = null;
  private peerConnection: RTCPeerConnection | null = null;
  private signalingClient: any = null;
  private webrtcConnected: boolean = false;
  private eventEmitter: EventEmitter;
  private audioCallback: ((data: ArrayBuffer) => void) | null = null;
  
  // 记录已添加的轨道，避免重复添加
  private addedTracks: MediaStreamTrack[] = [];

  /**
   * 构造函数
   * @param eventEmitter 事件发射器
   */
  constructor(eventEmitter: EventEmitter) {
    this.eventEmitter = eventEmitter;
  }

  /**
   * 设置SignalingClient实例
   * @param client SignalingClient实例
   */
  public setSignalingClient(client: any): void {
    this.signalingClient = client;
    console.log('[XIAOZHI-CLIENT] 已设置SignalingClient实例');
    this.setupSignalingEvents();
  }

  /**
   * 获取本地媒体流
   * @param constraints 媒体约束
   * @returns 包含本地媒体流的Promise
   */
  public async getLocalStream(constraints: MediaStreamConstraints): Promise<MediaStream> {
    if (this.localStream) {
      return this.localStream;
    }

    try {
      // 确保只请求音频
      const finalConstraints: MediaStreamConstraints = {
        audio: constraints.audio || true,
        video: false
      };

      // 获取媒体流
      this.localStream = await navigator.mediaDevices.getUserMedia(finalConstraints);
      console.log('[XIAOZHI-CLIENT] 已获取本地媒体流');
      
      return this.localStream;
    } catch (error) {
      console.error('[XIAOZHI-CLIENT] 获取本地媒体流失败:', error);
      throw error;
    }
  }

  /**
   * 停止并释放本地媒体流
   */
  public stopLocalStream(): void {
    if (this.localStream) {
      this.localStream.getTracks().forEach(track => {
        track.stop();
      });
      this.localStream = null;
      console.log('[XIAOZHI-CLIENT] 本地媒体流已停止');
    }
  }

  /**
   * 初始化音频处理
   * @param sampleRate 音频采样率
   * @returns 是否初始化成功
   */
  public initAudioProcessing(sampleRate: number = 16000): boolean {
    if (!this.localStream) {
      console.error('[XIAOZHI-CLIENT] 尚未获取本地媒体流，无法初始化音频处理');
      return false;
    }

    try {
      // 检查音频活动并设置监控
      this.monitorAudioActivity();

      // 使用标准WebRTC MediaStream API传输音频
      const audioTrack = this.localStream.getAudioTracks()[0];
      if (audioTrack) {
        // 输出音频轨道详细信息
        console.log('[XIAOZHI-CLIENT] 音频轨道信息:', {
          id: audioTrack.id,
          label: audioTrack.label,
          enabled: audioTrack.enabled,
          muted: audioTrack.muted,
          readyState: audioTrack.readyState
        });
        
        // 确保轨道已启用
        audioTrack.enabled = true;
        
        // 尝试设置音频约束
        const constraints: MediaTrackConstraints = {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true
        };
        console.log('[XIAOZHI-CLIENT] 应用兼容音频约束:', constraints);
        try {
          audioTrack.applyConstraints(constraints);
        } catch (e) {
          console.warn('[XIAOZHI-CLIENT] 应用音频约束失败，使用默认配置:', e);
        }
        
        // 将音频轨道添加到PeerConnection
        if (this.peerConnection && !this.addedTracks.includes(audioTrack)) {
          console.log('[XIAOZHI-CLIENT] 将音频轨道添加到PeerConnection');
          this.peerConnection.addTrack(audioTrack, this.localStream);
          this.addedTracks.push(audioTrack);
        }
      } else {
        console.warn('[XIAOZHI-CLIENT] 在媒体流中未找到音频轨道');
        return false;
      }

      console.log(`[XIAOZHI-CLIENT] 音频处理初始化成功，使用标准WebRTC MediaStream API`);
      return true;
    } catch (error) {
      console.error('[XIAOZHI-CLIENT] 初始化音频处理失败:', error);
      return false;
    }
  }

  /**
   * 停止音频处理
   */
  public stopAudioProcessing(): void {
    // 使用标准WebRTC MediaStream API，不需要手动停止处理
    console.log('[XIAOZHI-CLIENT] 音频处理已停止 (使用标准MediaStream API)');
  }

  /**
   * 设置音频回调
   * @param callback 音频数据回调函数
   */
  public setAudioCallback(callback: (data: ArrayBuffer) => void): void {
    this.audioCallback = callback;
    console.log('[XIAOZHI-CLIENT] 音频回调已设置，但使用标准MediaStream API时不会被调用');
  }

  /**
   * 监控音频活动以确保音频流动
   */
  private monitorAudioActivity(): void {
    try {
      if (!this.localStream) {
        console.error('[XIAOZHI-CLIENT] 无法监控音频活动: 没有本地媒体流');
        return;
      }

      const audioContext = new (window.AudioContext || (window as any).webkitAudioContext)();
      const source = audioContext.createMediaStreamSource(this.localStream);
      const analyser = audioContext.createAnalyser();
      analyser.fftSize = 256;
      source.connect(analyser);

      const bufferLength = analyser.frequencyBinCount;
      const dataArray = new Uint8Array(bufferLength);

      // 定期检测音频电平
      const checkAudioLevel = () => {
        if (!this.localStream) return;
        
        analyser.getByteFrequencyData(dataArray);
        
        // 计算音频电平平均值
        let sum = 0;
        for (let i = 0; i < bufferLength; i++) {
          sum += dataArray[i];
        }
        const average = sum / bufferLength;
        
        const audioTracks = this.localStream.getAudioTracks();
        if (audioTracks.length > 0) {
          const track = audioTracks[0];
          if (average > 0.1) {
            console.log(`[XIAOZHI-CLIENT] 检测到音频活动: 平均电平=${average.toFixed(2)}, 轨道状态=${track.readyState}, 活跃=${track.enabled}`);
          }
        }
      };

      // 每秒检测一次音频电平
      const intervalId = setInterval(checkAudioLevel, 1000);

      // 清理函数
      const cleanup = () => {
        clearInterval(intervalId);
        audioContext.close();
      };

      // 5分钟后停止监控
      setTimeout(cleanup, 5 * 60 * 1000);
    } catch (error) {
      console.error('[XIAOZHI-CLIENT] 监控音频活动失败:', error);
    }
  }

  /**
   * 释放所有资源
   */
  public dispose(): void {
    this.stopLocalStream();
    this.addedTracks = [];
  }

  /**
   * 设置PeerConnection实例
   * @param pc 外部传入的PeerConnection实例
   */
  public setPeerConnection(pc: RTCPeerConnection): void {
    this.peerConnection = pc;
    console.log('[XIAOZHI-CLIENT] 已设置外部PeerConnection实例');
    
    // 如果已有本地流，则添加轨道
    if (this.localStream) {
      const audioTrack = this.localStream.getAudioTracks()[0];
      if (audioTrack && !this.addedTracks.includes(audioTrack)) {
        console.log('[XIAOZHI-CLIENT] 将现有音频轨道添加到新设置的PeerConnection');
        this.peerConnection.addTrack(audioTrack, this.localStream);
        this.addedTracks.push(audioTrack);
      }
    }
  }
  
  /**
   * setDataChannel方法保留但不使用 - 使用标准MediaStream API不需要DataChannel传输音频
   * 保留此方法以兼容现有代码调用
   * @param channel 数据通道实例
   */
  public setDataChannel(channel: RTCDataChannel): void {
    console.log(`[XIAOZHI-CLIENT] setDataChannel被调用，但使用标准MediaStream API时不需要DataChannel传输音频`);
    // 不再存储或使用数据通道
  }

  /**
   * 设置信令消息处理
   */
  private setupSignalingEvents(): void {
    if (!this.signalingClient || !this.eventEmitter) return;

    // 监听ICE候选
    this.eventEmitter.on('ice-candidate', (payload: RTCIceCandidateInit) => {
      if (this.peerConnection) {
        console.log('[XIAOZHI-CLIENT-MEDIA] 收到ICE候选者，添加到连接');
        this.peerConnection.addIceCandidate(new RTCIceCandidate(payload))
          .catch(error => console.error('[XIAOZHI-CLIENT-MEDIA] 添加ICE候选者失败:', error));
      }
    });
  }
}