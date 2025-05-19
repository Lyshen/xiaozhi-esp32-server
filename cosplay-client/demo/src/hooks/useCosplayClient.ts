import { useState, useEffect, useCallback, useRef } from 'react';
import { CosplayClient, ClientEvent, ConnectionState, MessageType } from 'cosplay-client';

interface UseCosplayClientOptions {
  serverUrl: string;
  deviceId?: string;
  clientId?: string;
  autoConnect?: boolean;
}

interface Message {
  id: string;
  text: string;
  isUser: boolean;
  timestamp: number;
}

export function useCosplayClient({
  serverUrl = 'ws://172.22.0.2:8000/xiaozhi/v1/',
  deviceId = 'demo-device',
  clientId = 'cosplay-client-demo',
  autoConnect = true,
}: UseCosplayClientOptions) {
  const [connectionState, setConnectionState] = useState<ConnectionState>(ConnectionState.DISCONNECTED);
  const [messages, setMessages] = useState<Message[]>([]);
  const [isRecording, setIsRecording] = useState(false);
  const [isContinuousMode, setIsContinuousMode] = useState(false);
  
  // 使用useRef保存客户端实例，避免在重新渲染时重新创建
  const clientRef = useRef<CosplayClient | null>(null);
  
  // 初始化客户端
  useEffect(() => {
    if (!clientRef.current) {
      console.log('UseCosplayClient: Creating client with WebRTC enabled');
      
      // 创建CosplayClient实例
      clientRef.current = new CosplayClient({
        serverUrl,
        deviceId,
        clientId,
        reconnect: {
          enabled: true,
          maxAttempts: 5,
          delay: 2000,
        },
        audioConfig: {
          format: 'pcm', // 切换为PCM格式，配合WebRTC使用
          sampleRate: 16000,
          channels: 1,
          frameDuration: 20, // 使用更短的帧长度以减少延迟
          // WebRTC相关配置 - 明确指定为true
          useWebRTC: true, // 启用WebRTC
          webrtcSignalingUrl: 'ws://localhost:8082/ws/signaling', // 修正的信令服务器地址
          echoCancellation: true, // 启用回声消除
          noiseSuppression: true, // 启用噪声抑制
          autoGainControl: true, // 启用自动增益控制
        },
      });
      
      // 设置事件监听器
      setupEventListeners();
      
      // 自动连接
      if (autoConnect) {
        clientRef.current.connect();
      }
    }
    
    // 组件卸载时断开连接
    return () => {
      if (clientRef.current) {
        clientRef.current.disconnect();
        clientRef.current = null;
      }
    };
  }, [serverUrl, deviceId, clientId, autoConnect]);
  
  // 设置事件监听器
  const setupEventListeners = useCallback(() => {
    if (!clientRef.current) return;
    
    const client = clientRef.current;
    
    // 连接状态变化 - 仅更新状态，不添加到对话历史
    client.on(ClientEvent.CONNECTED, () => {
      setConnectionState(ConnectionState.CONNECTED);
      // 不要在对话框中添加连接状态消息
      // addSystemMessage('已连接到服务器');
      
      // 可以在控制台记录连接状态，但不影响UI
      console.log('已连接到服务器');
    });
    
    client.on(ClientEvent.DISCONNECTED, () => {
      setConnectionState(ConnectionState.DISCONNECTED);
      setIsRecording(false);
      // 不要在对话框中添加连接状态消息
      // addSystemMessage('已断开连接');
      
      // 可以在控制台记录连接状态，但不影响UI
      console.log('已断开连接');
    });
    
    // 语音识别结果
    client.on(ClientEvent.SPEECH_RECOGNITION, (data: any) => {
      if (data.final) {
        addUserMessage(data.text);
      }
    });
    
    // 错误处理
    client.on(ClientEvent.ERROR, (error: any) => {
      console.error('Client error:', error);
      addSystemMessage(`发生错误: ${error}`);
    });
    
    // 收到消息（可扩展处理不同类型的消息）
    client.on(ClientEvent.MESSAGE, (event: any) => {
      try {
        const data = JSON.parse(event.detail);
        if (data.type === MessageType.TEXT) {
          addAssistantMessage(data.text);
        }
      } catch (e) {
        // 处理非JSON消息（如二进制数据）
      }
    });
    
  }, []);
  
  // 添加消息到对话历史
  const addUserMessage = useCallback((text: string) => {
    setMessages(prev => [
      ...prev,
      {
        id: `user-${Date.now()}`,
        text,
        isUser: true,
        timestamp: Date.now()
      }
    ]);
  }, []);
  
  const addAssistantMessage = useCallback((text: string) => {
    setMessages(prev => [
      ...prev,
      {
        id: `assistant-${Date.now()}`,
        text,
        isUser: false,
        timestamp: Date.now()
      }
    ]);
  }, []);
  
  const addSystemMessage = useCallback((text: string) => {
    setMessages(prev => [
      ...prev,
      {
        id: `system-${Date.now()}`,
        text,
        isUser: false,
        timestamp: Date.now()
      }
    ]);
  }, []);
  
  // 连接/断开连接
  const connect = useCallback(() => {
    if (clientRef.current) {
      clientRef.current.connect();
    }
  }, []);
  
  const disconnect = useCallback(() => {
    if (clientRef.current) {
      clientRef.current.disconnect();
    }
  }, []);
  
  // 开始/停止录音
  const startRecording = useCallback(() => {
    if (clientRef.current && connectionState === ConnectionState.CONNECTED) {
      try {
        // 调用CosplayClient的startListening方法开始录音
        clientRef.current.startListening()
          .then(success => {
            if (success) {
              setIsRecording(true);
              console.log('开始录音成功');
            } else {
              console.error('开始录音失败');
            }
          })
          .catch(error => {
            console.error('开始录音错误:', error);
          });
      } catch (error) {
        console.error('开始录音失败:', error);
      }
    } else {
      console.log('无法录音: 未连接或客户端未初始化');
    }
  }, [connectionState]);
  
  const stopRecording = useCallback(() => {
    if (clientRef.current && isRecording) {
      try {
        // 调用CosplayClient的stopListening方法停止录音
        clientRef.current.stopListening();
        setIsRecording(false);
        console.log('停止录音');
      } catch (error) {
        console.error('停止录音失败:', error);
      }
    }
  }, [isRecording, clientRef]);
  
  // 发送文本消息
  const sendTextMessage = useCallback((text: string) => {
    if (clientRef.current && connectionState === ConnectionState.CONNECTED) {
      try {
        // 创建消息对象并进行发送（当实际API可用时解除注释）
        // const message = {
        //   type: MessageType.TEXT,
        //   text
        // };
        // clientRef.current.sendMessage(message);
        
        // 添加用户消息到UI
        addUserMessage(text);
      } catch (error) {
        console.error('Failed to send message:', error);
      }
    }
  }, [connectionState, addUserMessage]);
  
  // 切换持续录音模式
  const toggleContinuousMode = useCallback(() => {
    setIsContinuousMode(prev => !prev);
  }, []);
  
  // 清空消息历史
  const clearMessages = useCallback(() => {
    setMessages([]);
  }, []);
  
  return {
    connectionState,
    messages,
    isRecording,
    isContinuousMode,
    connect,
    disconnect,
    startRecording,
    stopRecording,
    sendTextMessage,
    toggleContinuousMode,
    clearMessages
  };
}
