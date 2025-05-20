import { EventEmitter } from 'events';
import { SignalingClient } from './signaling';
import { MediaManager } from './media-manager';
import { SignalingMessageType, WebRTCConfig, WebRTCConnectionState, WebRTCEvent } from '../../../types/webrtc';

/**
 * WebRTC音频连接
 * 负责管理WebRTC连接生命周期和音频传输
 */
export class WebRTCAudioConnection {
  private config: WebRTCConfig;
  private peerConnection: RTCPeerConnection | null = null;
  private signalingClient: SignalingClient;
  private mediaManager: MediaManager;
  private eventEmitter: EventEmitter;
  private state: WebRTCConnectionState = WebRTCConnectionState.NEW;
  private pendingCandidates: RTCIceCandidate[] = [];
  private isInitiator: boolean = false;
  private instanceId: string = `webrtc_${Math.random().toString(36).substring(2, 9)}_${Date.now()}`;

  /**
   * 构造函数
   * @param config WebRTC配置
   */
  constructor(config: WebRTCConfig) {
    console.log(`[DEBUG] WebRTCAudioConnection constructor called, instance ID: ${this.instanceId}`);
    this.config = config;
    this.eventEmitter = new EventEmitter();
    this.signalingClient = new SignalingClient(config.signalingUrl, this.eventEmitter);
    this.mediaManager = new MediaManager(this.eventEmitter);
    
    // 关键修复：将SignalingClient实例设置到MediaManager
    this.mediaManager.setSignalingClient(this.signalingClient);

    // 设置信令消息处理
    this.eventEmitter.on(SignalingMessageType.OFFER, this.handleRemoteOffer.bind(this));
    this.eventEmitter.on(SignalingMessageType.ANSWER, this.handleRemoteAnswer.bind(this));
    this.eventEmitter.on(SignalingMessageType.ICE_CANDIDATE, this.handleRemoteIceCandidate.bind(this));
    
    console.log(`[DEBUG] WebRTCAudioConnection constructor completed, instance ID: ${this.instanceId}`);
  }

  /**
   * 初始化WebRTC连接
   * @returns 初始化是否成功的Promise
   */
  public async initialize(): Promise<boolean> {
    try {
      console.log(`WebRTCAudioConnection[${this.instanceId}]: 开始初始化WebRTC连接`);
      
      // 创建RTCPeerConnection
      this.peerConnection = new RTCPeerConnection({
        iceServers: this.config.iceServers,
        iceTransportPolicy: this.config.iceTransportPolicy || 'all'
      });
      
      console.log(`WebRTCAudioConnection[${this.instanceId}]: RTCPeerConnection已创建, ICE服务器数量: ${this.config.iceServers.length}`);

      // 设置连接事件监听
      this.setupPeerConnectionListeners();
      
      // 添加音频transceiver并优先使用Opus编解码器
      const audioTransceiver = this.peerConnection.addTransceiver('audio', {
        direction: 'sendrecv'
      });
      
      // 明确设置Opus为首选编解码器
      if (RTCRtpSender.getCapabilities) {  // 检查浏览器支持
        const capabilities = RTCRtpSender.getCapabilities('audio');
        // 确保capabilities不为null
        if (capabilities && capabilities.codecs) {
          // 找到Opus编解码器并优先使用它
          const opusCodec = capabilities.codecs.find(codec => 
            codec.mimeType.toLowerCase() === 'audio/opus');
          
          if (opusCodec) {
            audioTransceiver.setCodecPreferences([opusCodec, ...capabilities.codecs.filter(c => 
              c.mimeType.toLowerCase() !== 'audio/opus')]);
            console.log('[XIAOZHI-CLIENT] 已将Opus设置为首选音频编解码器', opusCodec);
          }
        }
      }

      // 获取本地媒体流
      const stream = await this.mediaManager.getLocalStream({
        audio: {
          echoCancellation: this.config.echoCancellation !== false,
          noiseSuppression: this.config.noiseSuppression !== false,
          autoGainControl: this.config.autoGainControl !== false,
          sampleRate: this.config.sampleRate || 16000,
        },
        video: false
      });

      // 初始化音频处理
      this.mediaManager.initAudioProcessing(this.config.sampleRate || 16000);

      // 将音频轨道添加到对等连接
      stream.getAudioTracks().forEach(track => {
        if (this.peerConnection) {
          this.peerConnection.addTrack(track, stream);
        }
      });

      // 连接到信令服务器
      console.log(`WebRTCAudioConnection[${this.instanceId}]: 正在连接到信令服务器: ${this.config.signalingUrl}`);
      await this.signalingClient.connect();
      console.log(`WebRTCAudioConnection[${this.instanceId}]: 已成功连接到信令服务器`);

      this.setState(WebRTCConnectionState.CONNECTING);
      console.log(`WebRTCAudioConnection[${this.instanceId}]: 初始化完成，状态为 ${WebRTCConnectionState.CONNECTING}`);
      return true;
    } catch (error) {
      console.error(`WebRTCAudioConnection[${this.instanceId}]: 初始化错误:`, error);
      this.setState(WebRTCConnectionState.FAILED);
      this.eventEmitter.emit(WebRTCEvent.ERROR, error);
      return false;
    }
  }

  /**
   * 设置对等连接事件监听
   */
  private setupPeerConnectionListeners(): void {
    if (!this.peerConnection) return;
    
    console.log(`WebRTCAudioConnection[${this.instanceId}]: 设置对等连接事件监听器`);

    // ICE候选收集事件
    this.peerConnection.onicecandidate = (event) => {
      if (event.candidate) {
        console.log(`WebRTCAudioConnection[${this.instanceId}]: 收集到ICE候选，发送到信令服务器`);
        this.signalingClient.sendIceCandidate(event.candidate);
      }
    };

    // ICE连接状态变化事件
    this.peerConnection.oniceconnectionstatechange = () => {
      if (!this.peerConnection) return;
      
      console.log(`WebRTCAudioConnection[${this.instanceId}]: ICE连接状态变化为 ${this.peerConnection.iceConnectionState}`);
      
      switch (this.peerConnection.iceConnectionState) {
        case 'connected':
        case 'completed':
          if (this.state !== WebRTCConnectionState.CONNECTED) {
            this.setState(WebRTCConnectionState.CONNECTED);
            this.eventEmitter.emit(WebRTCEvent.CONNECTED);
            console.log(`WebRTCAudioConnection[${this.instanceId}]: WebRTC连接已建立，状态为 ${WebRTCConnectionState.CONNECTED}`);
          }
          break;
        case 'failed':
          console.error(`WebRTCAudioConnection[${this.instanceId}]: ICE连接失败`);
          if (this.state !== WebRTCConnectionState.FAILED) {
            this.setState(WebRTCConnectionState.FAILED);
            this.eventEmitter.emit(WebRTCEvent.ERROR, new Error('ICE connection failed'));
          }
          break;
        case 'disconnected':
          console.warn(`WebRTCAudioConnection[${this.instanceId}]: ICE连接断开，可能是暂时的网络问题`);
          if (this.state !== WebRTCConnectionState.DISCONNECTED) {
            this.setState(WebRTCConnectionState.DISCONNECTED);
            this.eventEmitter.emit(WebRTCEvent.DISCONNECTED);
          }
          break;
        case 'closed':
          console.log(`WebRTCAudioConnection[${this.instanceId}]: ICE连接已关闭`);
          this.setState(WebRTCConnectionState.CLOSED);
          this.eventEmitter.emit(WebRTCEvent.DISCONNECTED);
          break;
      }
    };

    // 接收轨道事件
    this.peerConnection.ontrack = (event) => {
      console.log(`WebRTCAudioConnection[${this.instanceId}]: 收到远程${event.track.kind}轨道, id: ${event.track.id}`);
      
      if (event.track.kind === 'audio') {
        // 创建包含远程音频轨道的媒体流
        const stream = new MediaStream([event.track]);
        console.log(`WebRTCAudioConnection[${this.instanceId}]: 已创建远程音频流`);
        
        // 触发音频接收事件
        this.eventEmitter.emit(WebRTCEvent.AUDIO_RECEIVED, stream);
        
        // 监听轨道状态变化
        event.track.onmute = () => {
          console.log(`WebRTCAudioConnection[${this.instanceId}]: 远程音频轨道已静音`);
        };
        
        event.track.onunmute = () => {
          console.log(`WebRTCAudioConnection[${this.instanceId}]: 远程音频轨道已取消静音`);
        };
        
        event.track.onended = () => {
          console.log(`WebRTCAudioConnection[${this.instanceId}]: 远程音频轨道已结束`);
        };
      }
    };
  }

  /**
   * 创建并发送offer
   * @returns 是否成功的Promise
   */
  public async createOffer(): Promise<boolean> {
    if (!this.peerConnection) {
      console.error(`WebRTCAudioConnection[${this.instanceId}]: 无法创建offer，对等连接未初始化`);
      return false;
    }

    try {
      // 设置为发起方
      this.isInitiator = true;
      console.log(`WebRTCAudioConnection[${this.instanceId}]: 开始创建Offer`);
      
      // 创建offer
      const offer = await this.peerConnection.createOffer({
        offerToReceiveAudio: true,
        offerToReceiveVideo: false
      });
      
      console.log(`WebRTCAudioConnection[${this.instanceId}]: Offer创建成功，设置本地描述`);
      
      // 设置本地描述
      await this.setLocalDescription(offer);
      
      // 发送offer
      console.log(`WebRTCAudioConnection[${this.instanceId}]: 发送Offer到信令服务器`);
      const sent = this.signalingClient.sendOffer(offer);
      if (!sent) {
        console.error(`WebRTCAudioConnection[${this.instanceId}]: 发送Offer失败`);
        return false;
      }
      
      console.log(`WebRTCAudioConnection[${this.instanceId}]: Offer发送成功`);
      return true;
    } catch (error) {
      console.error(`WebRTCAudioConnection[${this.instanceId}]: 创建Offer错误:`, error);
      return false;
    }
  }

  /**
   * 处理远程offer
   * @param offer 远程offer
   */
  private async handleRemoteOffer(offer: RTCSessionDescriptionInit): Promise<void> {
    if (!this.peerConnection) {
      console.error('WebRTCAudioConnection: Cannot handle offer without peer connection');
      return;
    }

    try {
      this.isInitiator = false;
      this.setState(WebRTCConnectionState.CONNECTING);
      
      // 设置远程描述
      await this.peerConnection.setRemoteDescription(new RTCSessionDescription(offer));
      console.log('WebRTCAudioConnection: Remote description (offer) set');
      
      // 添加之前收集的ICE候选
      await this.addPendingIceCandidates();
      
      // 创建answer
      const answer = await this.peerConnection.createAnswer();
      
      // 设置本地描述
      await this.setLocalDescription(answer);
      console.log('WebRTCAudioConnection: Local description (answer) set');
      
      // 发送answer
      this.signalingClient.sendAnswer(answer);
      console.log('WebRTCAudioConnection: Answer sent');
    } catch (error) {
      console.error('WebRTCAudioConnection: Error handling offer:', error);
      this.setState(WebRTCConnectionState.FAILED);
      this.eventEmitter.emit(WebRTCEvent.ERROR, error);
    }
  }

  /**
   * 处理远程answer
   * @param answer 远程answer
   */
  private async handleRemoteAnswer(answer: RTCSessionDescriptionInit): Promise<void> {
    if (!this.peerConnection || !this.isInitiator) {
      console.error('WebRTCAudioConnection: Cannot handle answer without being initiator');
      return;
    }

    try {
      // 设置远程描述
      await this.peerConnection.setRemoteDescription(new RTCSessionDescription(answer));
      console.log('WebRTCAudioConnection: Remote description (answer) set');
      
      // 添加之前收集的ICE候选
      await this.addPendingIceCandidates();
    } catch (error) {
      console.error('WebRTCAudioConnection: Error handling answer:', error);
      this.setState(WebRTCConnectionState.FAILED);
      this.eventEmitter.emit(WebRTCEvent.ERROR, error);
    }
  }

  /**
   * 处理远程ICE候选
   * @param candidate ICE候选
   */
  private async handleRemoteIceCandidate(candidate: RTCIceCandidateInit): Promise<void> {
    if (!this.peerConnection) {
      console.error('WebRTCAudioConnection: Cannot handle ICE candidate without peer connection');
      return;
    }

    try {
      // 如果远程描述尚未设置，先缓存候选
      if (!this.peerConnection.remoteDescription) {
        this.pendingCandidates.push(new RTCIceCandidate(candidate));
        console.log('WebRTCAudioConnection: ICE candidate stored for later use');
        return;
      }

      // 添加ICE候选
      await this.peerConnection.addIceCandidate(new RTCIceCandidate(candidate));
      console.log('WebRTCAudioConnection: Remote ICE candidate added');
    } catch (error) {
      console.error('WebRTCAudioConnection: Error handling ICE candidate:', error);
    }
  }

  /**
   * 添加待处理的ICE候选
   */
  private async addPendingIceCandidates(): Promise<void> {
    if (!this.peerConnection || !this.peerConnection.remoteDescription) {
      return;
    }

    try {
      // 添加所有待处理的ICE候选
      for (const candidate of this.pendingCandidates) {
        await this.peerConnection.addIceCandidate(candidate);
      }
      
      // 清空待处理列表
      this.pendingCandidates = [];
      console.log('WebRTCAudioConnection: Added all pending ICE candidates');
    } catch (error) {
      console.error('WebRTCAudioConnection: Error adding pending ICE candidates:', error);
    }
  }

  /**
   * 设置状态
   * @param state 新状态
   */
  private setState(state: WebRTCConnectionState): void {
    if (this.state !== state) {
      const prevState = this.state;
      this.state = state;
      console.log(`WebRTCAudioConnection[${this.instanceId}]: 状态从 ${prevState} 变为 ${state}`);
    }
  }

  /**
   * 获取当前状态
   * @returns 当前状态
   */
  public getState(): WebRTCConnectionState {
    return this.state;
  }

  /**
   * 设置音频回调
   * @param callback 音频数据回调函数
   */
  public setAudioCallback(callback: (data: ArrayBuffer) => void): void {
    this.mediaManager.setAudioCallback(callback);
  }

  /**
   * 注册事件监听器
   * @param event 事件名称
   * @param listener 监听函数
   */
  public on(event: string, listener: (...args: any[]) => void): void {
    this.eventEmitter.on(event, listener);
  }

  /**
   * 注册一次性事件监听器
   * @param event 事件名称
   * @param listener 监听函数
   */
  public once(event: string, listener: (...args: any[]) => void): void {
    this.eventEmitter.once(event, listener);
  }

  /**
   * 移除事件监听器
   * @param event 事件名称
   * @param listener 监听函数
   */
  public off(event: string, listener: (...args: any[]) => void): void {
    this.eventEmitter.removeListener(event, listener);
  }
  
  /**
   * 设置本地描述并捕获编解码器信息
   * @param description 本地描述
   */
  private async setLocalDescription(description: RTCSessionDescriptionInit): Promise<void> {
    if (!this.peerConnection) return;

    try {
      await this.peerConnection.setLocalDescription(description);
      
      // 保存编解码器信息，全局变量以便于日志记录
      this.saveCodecInfo(description.sdp);
    } catch (error) {
      console.error('WebRTCAudioConnection: Error setting local description:', error);
      throw error;
    }
  }
  
  /**
   * 从 SDP 中提取编解码器信息并保存
   * @param sdp SDP描述
   */
  private saveCodecInfo(sdp?: string): void {
    if (!sdp) return;

    try {
      // 解析SDP以获取编解码器信息
      const audioCodecRegex = /a=rtpmap:(\d+) ([\w\-/]+)/g;
      const codecMatches = [...sdp.matchAll(audioCodecRegex)];
      
      // 查找Opus编解码器
      const opusMatch = codecMatches.find(match => match[2].toLowerCase().includes('opus'));
      
      if (opusMatch) {
        const codecInfo = {
          payloadType: opusMatch[1],
          name: opusMatch[2],
          negotiated: true,
        };
        
        // 将编解码器信息存储在全局变量中
        (window as any).XIAOZHI_CODEC_INFO = codecInfo;
        
        // 将配置信息也存储在全局变量中
        (window as any).XIAOZHI_CONFIG = {
          audioConfig: this.config,
        };
        
        console.log('[XIAOZHI-CLIENT] 成功协商的编解码器:', codecInfo);
      } else {
        console.warn('[XIAOZHI-CLIENT] 在SDP中未找到Opus编解码器');
        (window as any).XIAOZHI_CODEC_INFO = { negotiated: false, reason: 'No Opus codec found in SDP' };
      }
    } catch (error) {
      console.error('[XIAOZHI-CLIENT] 解析编解码器信息时出错:', error);
    }
  }

  /**
   * 断开连接并清理资源
   */
  public disconnect(): void {
    console.log(`WebRTCAudioConnection[${this.instanceId}]: 正在断开连接并清理资源`);
    
    // 关闭媒体管理器
    this.mediaManager.dispose();
    
    // 关闭信令客户端
    this.signalingClient.disconnect();
    
    // 关闭对等连接
    if (this.peerConnection) {
      this.peerConnection.close();
      this.peerConnection = null;
      console.log(`WebRTCAudioConnection[${this.instanceId}]: 对等连接已关闭`);
    }
    
    this.setState(WebRTCConnectionState.CLOSED);
    console.log(`WebRTCAudioConnection[${this.instanceId}]: 所有资源已清理完毕`);
  }
  
  /**
   * 获取实例 ID
   * @returns 实例 ID
   */
  public getInstanceId(): string {
    return this.instanceId;
  }
}
