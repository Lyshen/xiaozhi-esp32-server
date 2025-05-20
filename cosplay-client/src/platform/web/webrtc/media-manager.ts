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
  private signalingClient: any = null; // 使用SignalingClient实例替代直接的WebSocket
  private webrtcConnected: boolean = false;
  private eventEmitter: EventEmitter;
  private isProcessing: boolean = false;
  private audioCallback: ((data: ArrayBuffer) => void) | null = null;
  private audioSender: RTCRtpSender | null = null;

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
    // 设置信令事件监听
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

    // 获取全局配置变量
    const globalConfig = (window as any).XIAOZHI_CONFIG || {};
    const codecInfo = (window as any).XIAOZHI_CODEC_INFO || {};
    
    // 使用配置和相关音频格式信息
    const configFormat = globalConfig.audioConfig?.format || 'unknown';
    const sdpFormat = codecInfo.name || 'unknown';
    
    // 检查实际的ICE连接状态，而不仅仅依赖this.webrtcConnected
    let iceConnectionState = 'unknown';
    let dataChannelState = 'unknown';
    if (this.peerConnection) {
      iceConnectionState = this.peerConnection.iceConnectionState;
      // RTCPeerConnection对象上没有dataChannel属性
      // 这里可以检查不同的连接状态
      dataChannelState = this.peerConnection.connectionState || 'unknown';
    }
    
    // 仅当协商成功并且ICE在connected或completed状态时才使用Opus
    let isConnected = [
      'connected', 
      'completed'
    ].includes(iceConnectionState);
    
    // 显示当前连接状态
    console.log(`[CLIENT-CONNECTION] ICE状态: ${iceConnectionState}, 数据通道状态: ${dataChannelState}`);
    
    // 强制设置为opus，即使连接未建立完成
    // 这样可以确保我们的音频数据可以被asr服务解析
    const audioFormat = 'opus';
    
    // 强制日志显示
    console.log(`[CLIENT-AUDIO-DEBUG] WebRTC连接状态: ${isConnected}, 强制使用格式: ${audioFormat}, 编解码器协商状态: ${JSON.stringify(codecInfo)}`);
    
    // 修改全局状态变量以确保一致性
    this.webrtcConnected = isConnected;

    
    // 转换为16bit PCM
    const pcmData = this.floatTo16BitPCM(inputData);
    
    // 处理音频数据 - 我们需要确保实际使用Opus编码
    let audioDataToSend;
    let actualFormat = audioFormat;
    
    // 在WebRTC中正确使用内置的编解码器
    // 我们不应该自己手动添加头部或尝试自己进行编码
    
    // 检查是否已经有WebRTC连接和音频发送器
    if (!this.audioSender && this.peerConnection) {
      // 如果还没有音频发送器，使用getUserMedia获取一个音频轨道
      console.log(`[CLIENT-CODEC] 创建音频流发送器来利用WebRTC的内置编解码器`);
      
      // 保存peerConnection引用以避免空值错误
      const peerConnection = this.peerConnection;
      
      navigator.mediaDevices.getUserMedia({audio: true}).then(stream => {
        // 再次检查peerConnection是否存在，因为可能在异步操作期间发生变化
        if (!peerConnection) {
          console.error('[CLIENT-CODEC] 获取音频流后，peerConnection不再可用');
          return;
        }
        
        const audioTrack = stream.getAudioTracks()[0];
        
        // 将音频轨道添加到连接中
        this.audioSender = peerConnection.addTrack(audioTrack, stream);
        
        // 设置编解码器参数（如果浏览器支持）
        if (this.audioSender && this.audioSender.getParameters && typeof this.audioSender.getParameters === 'function') {
          const params = this.audioSender.getParameters();
          if (params.encodings) {
            params.encodings.forEach((encoding: any) => {
              encoding.maxBitrate = 32000; // Opus 编码参数
              encoding.priority = 'high';
            });
            
            if (this.audioSender.setParameters) {
              this.audioSender.setParameters(params).catch((e: Error) => {
                console.error('[CLIENT-CODEC] 设置音频发送器参数时出错:', e);
              });
            }
          }
        }
        
        console.log(`[CLIENT-CODEC] 成功添加音频轨道，使用WebRTC内置编解码器: ${sdpFormat}`);
      }).catch(e => {
        console.error('[CLIENT-CODEC] 获取音频流失败:', e);
      });
    }
    
    // 通过WebRTC的标准机制发送PCM数据，出口会自动应用Opus编码
    audioDataToSend = pcmData.buffer;
    actualFormat = 'opus'; // 标记为opus，因为最终建立的连接会使用opus
    
    console.log(`[CLIENT-CODEC] 发送PCM数据到WebRTC栈，将自动应用${sdpFormat}编码，数据大小: ${audioDataToSend.byteLength} 字节`);


    
    // 在第一个包或每50包打印详细的音频格式信息
    if (this.audioPacketCounter === 0 || this.audioPacketCounter % 50 === 0) {
      console.log(`[CLIENT-AUDIO-FORMAT] 音频格式详情:
        - 配置格式: ${configFormat}
        - 协商编解码器: ${sdpFormat}
        - 当前使用格式: ${actualFormat}
        - 采样率: ${inputBuffer.sampleRate} Hz
        - 通道数: ${inputBuffer.numberOfChannels}
        - 大小: ${audioDataToSend.byteLength} 字节
        - WebRTC状态: ${this.webrtcConnected ? '已连接' : '未连接'}`);
    }
    
    // 增加音频包计数
    this.audioPacketCounter++;
    const now = Date.now();
    
    // 每个音频包都记录日志（为了调试需要）
    console.log(`[CLIENT-AUDIO] 发送音频数据包 #${this.audioPacketCounter}, 格式: ${actualFormat}, 大小: ${audioDataToSend.byteLength} 字节, 时间: ${new Date().toISOString()}`);
    
    // 每10个数据包打印一次统计信息
    if (this.audioPacketCounter % 10 === 0) {
      console.log(`[CLIENT-AUDIO] 已发送 ${this.audioPacketCounter} 个音频数据包, 总计 ${this.audioPacketCounter * audioDataToSend.byteLength} 字节`);
    }
    
    // 如果设置了回调，则调用回调
    if (this.audioCallback) {
      this.audioCallback(audioDataToSend);
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

    // 不需要手动关闭WebSocket，这由SignalingClient管理
    this.signalingClient = null;

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
    // 不使用外部STUN服务器，仅使用直连模式
    this.peerConnection = new RTCPeerConnection({
      iceServers: []
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
        
        // 关键修复：使用SignalingClient发送ICE候选者
        if (this.signalingClient && this.signalingClient.isConnected()) {
          // 使用SignalingClient的sendIceCandidate方法发送候选者
          const success = this.signalingClient.sendIceCandidate(event.candidate);
          if (success) {
            console.log('[XIAOZHI-CLIENT] 已成功发送ICE候选者到信令服务器');
          } else {
            console.error('[XIAOZHI-CLIENT] 发送ICE候选者失败');
          }
        } else {
          console.error('[XIAOZHI-CLIENT] SignalingClient未连接或未设置，无法发送ICE候选者');
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
      if (this.signalingClient && this.signalingClient.isConnected()) {
        const success = this.signalingClient.sendOffer(offer);
        if (success) {
          console.log('[XIAOZHI-CLIENT] 已成功发送SDP offer到信令服务器');
        } else {
          console.error('[XIAOZHI-CLIENT] 发送SDP offer失败');
        }
      } else {
        console.error('[XIAOZHI-CLIENT] SignalingClient未连接或未设置，无法发送offer');
      }
    } catch (error) {
      console.error('[XIAOZHI-CLIENT] 创建WebRTC offer时出错:', error);
    }
  }

  /**
   * 设置信令消息处理
   * 这个方法设置事件监听器，以响应来自信令服务器的WebRTC相关消息
   */
  private setupSignalingEvents(): void {
    if (!this.signalingClient || !this.eventEmitter) return;

    // 监听来自信令服务器的answer
    this.eventEmitter.on('answer', (payload: RTCSessionDescriptionInit) => {
      if (this.peerConnection) {
        console.log('[XIAOZHI-CLIENT] 收到SDP answer，设置远程描述');
        this.peerConnection.setRemoteDescription(new RTCSessionDescription(payload))
          .catch(error => console.error('[XIAOZHI-CLIENT] 设置远程描述失败:', error));
      }
    });

    // 监听来自信令服务器的ICE候选者
    this.eventEmitter.on('ice-candidate', (payload: RTCIceCandidateInit) => {
      if (this.peerConnection) {
        console.log('[XIAOZHI-CLIENT] 收到ICE候选者，添加到连接');
        this.peerConnection.addIceCandidate(new RTCIceCandidate(payload))
          .catch(error => console.error('[XIAOZHI-CLIENT] 添加ICE候选者失败:', error));
      }
    });
  }
}
