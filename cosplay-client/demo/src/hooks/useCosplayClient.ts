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
  serverUrl = 'ws://localhost:8000/ws',
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
          format: 'pcm',
          sampleRate: 16000,
          channels: 1,
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
    
    // 连接状态变化
    client.on(ClientEvent.CONNECTED, () => {
      setConnectionState(ConnectionState.CONNECTED);
      addSystemMessage('已连接到服务器');
    });
    
    client.on(ClientEvent.DISCONNECTED, () => {
      setConnectionState(ConnectionState.DISCONNECTED);
      setIsRecording(false);
      addSystemMessage('已断开连接');
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
      // 假设客户端有开始录音的方法
      // 根据实际API调整
      try {
        // 客户端在这里可能会有startRecording、startAudioCapture或类似的方法
        // clientRef.current.startRecording();
        setIsRecording(true);
      } catch (error) {
        console.error('Failed to start recording:', error);
      }
    }
  }, [connectionState]);
  
  const stopRecording = useCallback(() => {
    if (clientRef.current && isRecording) {
      // 假设客户端有停止录音的方法
      // 根据实际API调整
      try {
        // clientRef.current.stopRecording();
        setIsRecording(false);
      } catch (error) {
        console.error('Failed to stop recording:', error);
      }
    }
  }, [isRecording]);
  
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
