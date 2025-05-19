import { EventEmitter } from 'events';
import { WebRTCEvent } from '../../../types/webrtc';

/**
 * WebRTC媒体管理器
 * 负责管理媒体流的获取、处理和释放
 */
export class MediaManager {
  private localStream: MediaStream | null = null;
  private audioContext: AudioContext | null = null;
  private mediaSource: MediaStreamAudioSourceNode | null = null;
  private audioProcessor: ScriptProcessorNode | null = null;
  private peerConnection: RTCPeerConnection | null = null;
  private websocket: WebSocket | null = null;
  private webrtcConnected: boolean = false;
  private eventEmitter: EventEmitter;
  private isProcessing: boolean = false;
  private audioCallback: ((data: ArrayBuffer) => void) | null = null;

  /**
   * 构造函数
   * @param eventEmitter 事件发射器
   */
  constructor(eventEmitter: EventEmitter) {
    this.eventEmitter = eventEmitter;
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
      console.log('MediaManager: Local media stream obtained');
      
      return this.localStream;
    } catch (error) {
      console.error('MediaManager: Error getting local media stream:', error);
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
      console.log('MediaManager: Local media stream stopped');
    }
  }

  /**
   * 初始化音频处理
   * @param sampleRate 采样率
   * @returns 是否初始化成功
   */
  public initAudioProcessing(sampleRate: number = 16000): boolean {
    if (!this.localStream) {
      console.error('MediaManager: Cannot initialize audio processing without a local stream');
      return false;
    }

    try {
      // 创建音频上下文
      this.audioContext = new (window.AudioContext || (window as any).webkitAudioContext)({
        sampleRate: sampleRate
      });

      // 创建媒体源节点
      this.mediaSource = this.audioContext.createMediaStreamSource(this.localStream);

      // 创建处理节点
      // 注：ScriptProcessorNode已被标记为废弃，将来可能需要迁移到AudioWorklet
      // 使用较小的缓冲区大小
      this.audioProcessor = this.audioContext.createScriptProcessor(1024, 1, 1);
      this.audioProcessor.onaudioprocess = this.handleAudioProcess.bind(this);

      // 连接节点
      this.mediaSource.connect(this.audioProcessor);
      this.audioProcessor.connect(this.audioContext.destination);
      
      // 获取媒体流上的音频轨道并应用兼容的音频约束
      // 关键修复：移除了不兼容的sampleRate约束
      const audioTrack = this.localStream.getAudioTracks()[0];
      if (audioTrack) {
        const constraints = {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true
        };
        console.log('[XIAOZHI-CLIENT] 应用兼容音频约束:', constraints);
        audioTrack.applyConstraints(constraints).catch(error => {
          console.warn('[XIAOZHI-CLIENT] 应用音频约束失败，使用默认设置:', error);
        });
      }

      // 初始化WebRTC连接
      this.initWebRTCConnection();

      this.isProcessing = true;
      console.log('MediaManager: Audio processing initialized with WebRTC');
      return true;
    } catch (error) {
      console.error('MediaManager: Failed to initialize audio processing:', error);
      return false;
    }
  }

  // 添加音频包计数
  private audioPacketCounter: number = 0;
  private lastLogTime: number = 0;

  /**
   * 处理音频数据
   * @param event 音频处理事件
   */
  private handleAudioProcess(event: AudioProcessingEvent): void {
    if (!this.isProcessing) return;

    // 获取输入缓冲区
    const inputBuffer = event.inputBuffer;
    const inputData = inputBuffer.getChannelData(0);

    // 转换为16bit PCM
    const pcmData = this.floatTo16BitPCM(inputData);
    
    // 增加音频包计数
    this.audioPacketCounter++;
    const now = Date.now();
    
    // 每个音频包都记录日志（为了调试需要）
    console.log(`[CLIENT-AUDIO] 发送音频数据包 #${this.audioPacketCounter}, 大小: ${pcmData.buffer.byteLength} 字节, 时间: ${new Date().toISOString()}`);
    
    // 每10个数据包打印一次统计信息
    if (this.audioPacketCounter % 10 === 0) {
      console.log(`[CLIENT-AUDIO] 已发送 ${this.audioPacketCounter} 个音频数据包, 总计 ${this.audioPacketCounter * pcmData.buffer.byteLength} 字节`);
    }
    
    // 如果设置了回调，则调用回调
    if (this.audioCallback) {
      this.audioCallback(pcmData.buffer);
    }

    // 发出事件
    this.eventEmitter.emit(WebRTCEvent.AUDIO_SENT, pcmData.buffer);
  }

  /**
   * 将Float32Array转换为Int16Array (16bit PCM)
   * 并调整数据形状以适应服务器期望的[1, samples]而非[4096, samples]
   * @param input Float32Array输入
   * @returns Int16Array (16bit PCM)
   */
  private floatTo16BitPCM(input: Float32Array): Int16Array {
    // 创建一个只有1行的数组(以适应服务器期望的形状)
    const output = new Int16Array(input.length);
    
    for (let i = 0; i < input.length; i++) {
      // 将-1.0到1.0的浮点数转换为-32768到32767的整数
      const s = Math.max(-1, Math.min(1, input[i]));
      output[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
    }
    
    // 返回调整后的数组
    return output;
  }

  /**
   * 停止音频处理
   */
  public stopAudioProcessing(): void {
    this.isProcessing = false;

    // 关闭WebRTC连接
    if (this.peerConnection) {
      this.peerConnection.close();
      this.peerConnection = null;
    }

    // 关闭WebSocket连接
    if (this.websocket) {
      this.websocket.close();
      this.websocket = null;
    }

    if (this.audioProcessor) {
      this.audioProcessor.disconnect();
      this.audioProcessor = null;
    }

    if (this.mediaSource) {
      this.mediaSource.disconnect();
      this.mediaSource = null;
    }

    if (this.audioContext && this.audioContext.state !== 'closed') {
      this.audioContext.close();
      this.audioContext = null;
    }

    this.webrtcConnected = false;
    console.log('MediaManager: Audio processing stopped');
  }

  /**
   * 设置音频数据回调
   * @param callback 音频数据回调函数
   */
  public setAudioCallback(callback: (data: ArrayBuffer) => void): void {
    this.audioCallback = callback;
  }

  /**
   * 释放所有资源
   */
  public dispose(): void {
    this.stopAudioProcessing();
    this.stopLocalStream();
  }

  /**
   * 初始化WebRTC连接
   */
  private async initWebRTCConnection(): Promise<void> {
    console.log('[XIAOZHI-CLIENT] 开始初始化WebRTC连接');
    
    // 创建RTC对等连接
    this.peerConnection = new RTCPeerConnection({
      iceServers: [
        { urls: 'stun:stun.l.google.com:19302' },
        { urls: 'stun:stun1.l.google.com:19302' }
      ]
    });

    // 监控ICE连接状态变化
    this.peerConnection.oniceconnectionstatechange = () => {
      if (this.peerConnection) {
        console.log(`[XIAOZHI-CLIENT] WebRTC ICE连接状态变化: ${this.peerConnection.iceConnectionState}`);
        
        if (this.peerConnection.iceConnectionState === 'connected') {
          this.webrtcConnected = true;
          console.log('[XIAOZHI-CLIENT] WebRTC连接已建立，准备传输音频数据');
          this.eventEmitter.emit(WebRTCEvent.CONNECTED);
        } else if (this.peerConnection.iceConnectionState === 'disconnected' || 
                  this.peerConnection.iceConnectionState === 'failed') {
          this.webrtcConnected = false;
          console.log('[XIAOZHI-CLIENT] WebRTC连接已断开');
          this.eventEmitter.emit(WebRTCEvent.DISCONNECTED);
        }
      }
    };
    
    // 监控ICE候选者收集
    this.peerConnection.onicecandidate = (event) => {
      if (event.candidate) {
        console.log('[XIAOZHI-CLIENT] 发现新的ICE候选者');
        
        // 关键修复：确保ICE候选者被正确发送到信令服务器
        if (this.websocket && this.websocket.readyState === WebSocket.OPEN) {
          const iceCandidateMessage = {
            type: 'ice-candidate',
            candidate: event.candidate
          };
          this.websocket.send(JSON.stringify(iceCandidateMessage));
          console.log('[XIAOZHI-CLIENT] 已发送ICE候选者到信令服务器');
        } else {
          console.error('[XIAOZHI-CLIENT] WebSocket未连接，无法发送ICE候选者');
        }
      }
    };

    // 添加本地音频轨道
    if (this.localStream) {
      this.localStream.getAudioTracks().forEach(track => {
        this.peerConnection?.addTrack(track, this.localStream!);
        console.log('[XIAOZHI-CLIENT] 音频轨道已添加到WebRTC连接');
      });
    }

    try {
      // 创建offer
      const offer = await this.peerConnection.createOffer({
        offerToReceiveAudio: true,
        offerToReceiveVideo: false
      });

      // 设置本地描述
      await this.peerConnection.setLocalDescription(offer);
      console.log('[XIAOZHI-CLIENT] 本地SDP设置完成');

      // 发送offer到信令服务器
      if (this.websocket && this.websocket.readyState === WebSocket.OPEN) {
        const offerMessage = {
          type: 'offer',
          sdp: offer.sdp
        };
        this.websocket.send(JSON.stringify(offerMessage));
        console.log('[XIAOZHI-CLIENT] 已发送SDP offer到信令服务器');
      } else {
        console.error('[XIAOZHI-CLIENT] WebSocket未连接，无法发送offer');
      }
    } catch (error) {
      console.error('[XIAOZHI-CLIENT] 创建WebRTC offer时出错:', error);
    }
  }

  /**
   * 连接到WebSocket信令服务器
   * @param url WebSocket服务器URL
   */
  public async connectToSignalingServer(url: string): Promise<void> {
    return new Promise((resolve, reject) => {
      try {
        this.websocket = new WebSocket(url);
        
        this.websocket.onopen = () => {
          console.log('[XIAOZHI-CLIENT] WebSocket连接已建立');
          resolve();
        };
        
        this.websocket.onerror = (error) => {
          console.error('[XIAOZHI-CLIENT] WebSocket连接错误:', error);
          reject(error);
        };
        
        this.websocket.onclose = () => {
          console.log('[XIAOZHI-CLIENT] WebSocket连接已关闭');
          this.webrtcConnected = false;
        };
        
        this.websocket.onmessage = this.handleSignalingMessage.bind(this);
      } catch (error) {
        console.error('[XIAOZHI-CLIENT] 连接到信令服务器时出错:', error);
        reject(error);
      }
    });
  }

  /**
   * 处理来自信令服务器的消息
   */
  private handleSignalingMessage(event: MessageEvent): void {
    try {
      const message = JSON.parse(event.data);
      console.log('[XIAOZHI-CLIENT] 收到信令消息:', message.type);
      
      // 处理不同类型的信令消息
      if (message.type === 'ice-candidate' && this.peerConnection) {
        // 添加ICE候选者
        this.peerConnection.addIceCandidate(new RTCIceCandidate(message.candidate))
          .catch(error => console.error('[XIAOZHI-CLIENT] 添加ICE候选者失败:', error));
      } else if (message.type === 'answer' && this.peerConnection) {
        // 设置远程描述（answer）
        this.peerConnection.setRemoteDescription(new RTCSessionDescription(message))
          .catch(error => console.error('[XIAOZHI-CLIENT] 设置远程描述失败:', error));
      }
    } catch (error) {
      console.error('[XIAOZHI-CLIENT] 处理信令消息时出错:', error);
    }
  }
}
