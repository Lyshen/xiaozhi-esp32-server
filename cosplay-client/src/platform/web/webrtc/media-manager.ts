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
  private signalingClient: any = null;
  private webrtcConnected: boolean = false;
  private eventEmitter: EventEmitter;
  private isProcessing: boolean = false;
  private audioCallback: ((data: ArrayBuffer) => void) | null = null;
  private audioPacketCounter: number = 0;
  private lastLogTime: number = 0;
  
  // WebRTC数据通道相关
  private dataChannel: RTCDataChannel | null = null;
  private totalBytesSent: number = 0;

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

      // 注意: 现在不需要在这里初始化WebRTC连接
      // 因为PeerConnection现在是从外部设置的

      this.isProcessing = true;
      console.log('MediaManager: Audio processing initialized with WebRTC');
      return true;
    } catch (error) {
      console.error('MediaManager: Failed to initialize audio processing:', error);
      return false;
    }
  }

  /**
   * 处理音频数据
   * @param event 音频处理事件
   */
  private handleAudioProcess(event: AudioProcessingEvent): void {
    try {
      if (!this.isProcessing) {
        return; // 如果没有在处理音频，直接返回
      }

      // 获取输入数据
      const inputData = event.inputBuffer.getChannelData(0);
      
      // 转换为16位整数
      const pcmData = this.floatTo16BitPCM(inputData);
      
      // 增加包计数器
      this.audioPacketCounter++;
      
      // 计算数据大小
      const pcmDataSize = pcmData.buffer.byteLength;
      
      // 检查WebRTC连接状态
      let webrtcState = '未连接';
      let iceState = '未知';
      let dataChannelState = '未创建';
      
      if (this.peerConnection) {
        webrtcState = this.webrtcConnected ? '已连接' : '连接中';
        iceState = this.peerConnection.iceConnectionState;
        
        if (this.dataChannel) {
          dataChannelState = this.dataChannel.readyState;
        }
      }
      
      // 每20个包输出一次详细日志
      if (this.audioPacketCounter % 20 === 0) {
        console.log(`[P2P-TX-DEBUG] 音频包 #${this.audioPacketCounter} 准备发送: ` + 
                   `采样率=${event.inputBuffer.sampleRate}Hz, ` + 
                   `大小=${pcmDataSize} 字节, ` + 
                   `WebRTC状态=${webrtcState}, ` + 
                   `ICE状态=${iceState}, ` + 
                   `数据通道=${dataChannelState}`);
      }
      
      // 1. 优先通过WebRTC DataChannel发送数据
      if (this.webrtcConnected && this.dataChannel && this.dataChannel.readyState === 'open') {
        try {
          // 创建音频数据包
          const audioPacket = {
            id: this.audioPacketCounter,
            timestamp: Date.now(),
            sampleRate: event.inputBuffer.sampleRate,
            data: Array.from(pcmData)  // 转换为数组以便JSON序列化
          };
          
          // 发送数据
          this.dataChannel.send(JSON.stringify(audioPacket));
          this.totalBytesSent += pcmDataSize;
          
          // 每50个包输出一次数据发送日志
          if (this.audioPacketCounter % 50 === 0) {
            console.log(`[P2P-DATA-SENT] 通过WebRTC数据通道发送音频包 #${this.audioPacketCounter}, ` + 
                      `大小: ${pcmDataSize} 字节, 累计: ${this.totalBytesSent} 字节`);
          }
        } catch (e) {
          console.error('[P2P-TX-ERROR] 通过数据通道发送音频数据失败:', e);
        }
      }
      
      // 2. 如果有回调，也使用传统方式发送数据
      if (this.audioCallback) {
        // 全量日志只在特定包号输出
        if (this.audioPacketCounter === 1 || this.audioPacketCounter % 100 === 0) {
          console.log(`[CLIENT-AUDIO] 音频包 #${this.audioPacketCounter}, 采样率: ${event.inputBuffer.sampleRate}Hz, 大小: ${pcmDataSize} 字节`);
        }
        
        // 发送数据到回调
        this.audioCallback(pcmData.buffer);
        
        // 发出事件
        this.eventEmitter.emit(WebRTCEvent.AUDIO_SENT, pcmData.buffer);
      }
    } catch (error) {
      console.error('[P2P-TX-ERROR] 处理音频数据错误:', error);
    }
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
   * 设置PeerConnection实例
   * @param pc 外部传入的PeerConnection实例
   */
  public setPeerConnection(pc: RTCPeerConnection): void {
    console.log('[XIAOZHI-CLIENT] 设置外部PeerConnection实例');
    this.peerConnection = pc;
    this.setupConnectionEvents();
  }

  /**
   * 处理ICE状态变化
   */
  private async handleIceConnectionChange(): Promise<void> {
    if (!this.peerConnection) return;
    
    // 在这里添加处理ICE状态变化的代码
    console.log(`[XIAOZHI-CLIENT] ICE状态变化: ${this.peerConnection.iceConnectionState}`);
  }
  
  /**
   * 建立WebRTC连接
   */
  public async connect(): Promise<void> {
    console.log('[XIAOZHI-CLIENT] 开始建立WebRTC连接...');
    
    try {
      this.close(); // 先关闭已有连接
      // 注意：不再调用initWebRTCConnection，因为PeerConnection现在从外部设置
      // 现在仅设置事件监听
      if (this.peerConnection) {
        this.setupConnectionEvents();
      } else {
        console.error('[XIAOZHI-CLIENT] 无法建立连接，PeerConnection未设置');
      }
    } catch (error) {
      console.error('[XIAOZHI-CLIENT] 建立WebRTC连接失败:', error);
      throw error;
    }
  }

  /**
   * 设置WebRTC连接事件监听
   */
  private setupConnectionEvents(): void {
    if (!this.peerConnection) {
      console.error('[XIAOZHI-CLIENT] 无法设置连接事件，PeerConnection不存在');
      return;
    }
    
    // 监控ICE连接状态变化
    this.peerConnection.addEventListener('iceconnectionstatechange', () => {
      console.log(`[XIAOZHI-CLIENT] WebRTC oniceconnectionstatechange in MediaManager`);
      if (!this.peerConnection) return;
      
      const iceState = this.peerConnection.iceConnectionState;
      console.log(`[XIAOZHI-CLIENT] MediaManager ICE连接状态变化: ${iceState}`);
      
      if (iceState === 'connected' || iceState === 'completed') {
        this.webrtcConnected = true;
        console.log(`[XIAOZHI-CLIENT] MediaManager WebRTC连接已建立 (${iceState})，准备传输音频数据`);

        // 在连接建立成功后创建DataChannel
        if (!this.dataChannel) {
          try {
            console.log('[P2P-DATACHANNEL] MediaManager中连接已建立，创建DataChannel...');
            
            this.dataChannel = this.peerConnection.createDataChannel('audioData', {
              ordered: true,  // 有序传输
              maxRetransmits: 10  // 最多重传10次
            });
            
            const channelId = this.dataChannel ? this.dataChannel.id : 'unknown';
            console.log(`[P2P-DATACHANNEL] 数据通道已创建，等待打开，ID: ${channelId}`);
            
            // 设置DataChannel事件
            this.dataChannel.onopen = () => {
              if (this.dataChannel) {
                console.log(`[P2P-DATACHANNEL] 数据通道已打开，标签: ${this.dataChannel.label}, 状态: ${this.dataChannel.readyState}`);
              }
            };
            
            this.dataChannel.onclose = () => {
              console.log('[P2P-DATACHANNEL] 数据通道已关闭');
            };
            
            this.dataChannel.onerror = (event: Event) => {
              console.error('[P2P-DATACHANNEL] 数据通道错误:', event);
            };
          } catch (e) {
            console.error('[P2P-DATACHANNEL] 创建DataChannel失败:', e);
          }
        }
      } else if (iceState === 'disconnected' || iceState === 'failed' || iceState === 'closed') {
        this.webrtcConnected = false;
        console.log('[XIAOZHI-CLIENT] MediaManager WebRTC连接已断开');
        this.eventEmitter.emit(WebRTCEvent.DISCONNECTED);
        
        // 清理数据通道
        if (this.dataChannel) {
          console.log('[P2P-DATACHANNEL] 关闭数据通道');
          this.dataChannel = null;
        }
      }
    });
  }

  /**
   * 关闭并清理WebRTC连接
   */
  public close(): void {
    console.log('[XIAOZHI-CLIENT] 关闭并清理WebRTC连接');
    
    // 清理数据通道
    if (this.dataChannel) {
      if (this.dataChannel.readyState === 'open') {
        try {
          this.dataChannel.close();
        } catch (e) {
          console.error('[P2P-DATACHANNEL] 关闭数据通道时出错:', e);
        }
      }
      this.dataChannel = null;
    }
    
    // 设置连接状态
    this.webrtcConnected = false;
    
    // 注意：不在这里关闭PeerConnection，因为它现在属于外部管理
  }

  /**
   * 设置信令消息处理
   * 这个方法设置事件监听器，以响应来自信令服务器的WebRTC相关消息
   * 注意: 现在不在MediaManager中处理SDP，而是在WebRTCAudioConnection中统一处理
   */
  private setupSignalingEvents(): void {
    if (!this.signalingClient || !this.eventEmitter) return;

    // 注意: 不再监听'answer'事件，这已在WebRTCAudioConnection中处理
    // 避免重复设置RemoteDescription导致出错

    // 仅监听其他必要的WebRTC事件
    this.eventEmitter.on('ice-candidate', (payload: RTCIceCandidateInit) => {
      if (this.peerConnection) {
        console.log('[XIAOZHI-CLIENT-MEDIA] 收到ICE候选者，添加到连接');
        this.peerConnection.addIceCandidate(new RTCIceCandidate(payload))
          .catch(error => console.error('[XIAOZHI-CLIENT-MEDIA] 添加ICE候选者失败:', error));
      }
    });
  }
}
