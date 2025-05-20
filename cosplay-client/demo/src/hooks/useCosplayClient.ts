import { useState, useEffect, useCallback, useRef } from 'react';
import { CosplayClient, ClientEvent, ConnectionState, MessageType } from 'cosplay-client';

// Global singleton instance to persist across component remounts
let globalClientInstance: CosplayClient | null = null;

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
    console.log(`[DEBUG] useCosplayClient useEffect - globalClientInstance: ${!!globalClientInstance}, clientRef.current: ${!!clientRef.current}, autoConnect: ${autoConnect}`);
    
    // 使用全局单例模式确保只创建一次客户端实例
    if (!globalClientInstance) {
      console.log('[DEBUG] UseCosplayClient: Creating NEW client with WebRTC enabled (global singleton)');
      
      // 创建CosplayClient实例
      globalClientInstance = new CosplayClient({
        serverUrl,
        deviceId,
        clientId,
        reconnect: {
          enabled: true,
          maxAttempts: 5,
          delay: 2000,
        },
        audioConfig: {
          format: 'opus', // 使用Opus格式以获得更好的音频质量
          sampleRate: 16000,
          channels: 1,
          frameDuration: 20, // 使用更短的帧长度以减少延迟
          // WebRTC相关配置 - 明确指定为true
          useWebRTC: true, // 启用WebRTC
          webrtcSignalingUrl: 'ws://localhost:8082/ws/signaling', // 改回使用localhost，因为可能8082端口映射到本地
          echoCancellation: true, // 启用回声消除
          noiseSuppression: true, // 启用噪声抑制
          autoGainControl: true, // 启用自动增益控制
        },
      });
      
      console.log('[DEBUG] Global client singleton created');
    } else {
      console.log('[DEBUG] Using EXISTING global client instance');
    }
    
    // 将全局实例分配给当前组件的ref
    clientRef.current = globalClientInstance;
    
    // 设置事件监听器 - 每次组件挂载时都需要重新设置
    console.log('[DEBUG] Setting up event listeners');
    setupEventListeners();
    
    // 自动连接 - 仅在初始化后执行一次
    // 将连接逻辑移到这里，而不是放在客户端创建内部
    // 这样可以避免重复连接
    if (clientRef.current && autoConnect) {
      const currentState = clientRef.current.getConnectionState();
      console.log(`[DEBUG] Connection check - current state: ${currentState}`);
      
      if (currentState === ConnectionState.DISCONNECTED) {
        console.log('[DEBUG] Client disconnected, attempting to connect');
        clientRef.current.connect();
      } else {
        console.log(`[DEBUG] Client already in state: ${currentState}, not connecting`);
      }
    }
    
    // 组件卸载时不需要销毁全局实例，只需要清理当前组件的引用
    return () => {
      console.log('[DEBUG] Component unmounting, NOT destroying global client instance');
      // 只清理当前组件的引用，不销毁全局实例
      clientRef.current = null;
    };
  }, [serverUrl, deviceId, clientId, autoConnect, isRecording]);
  
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
  
  // 设置事件监听器 - 移动到消息处理函数之后，避免引用错误
  const setupEventListeners = useCallback(() => {
    if (!clientRef.current) return;
    
    const client = clientRef.current;
    
    // 先移除所有现有的事件监听器，防止重复添加
    client.off(ClientEvent.CONNECTED, () => {});
    client.off(ClientEvent.DISCONNECTED, () => {});
    client.off(ClientEvent.SPEECH_RECOGNITION, () => {});
    client.off(ClientEvent.ERROR, () => {});
    client.off(ClientEvent.MESSAGE, () => {});
    
    // 连接状态变化 - 仅更新状态，不添加到对话历史
    client.on(ClientEvent.CONNECTED, () => {
      setConnectionState(ConnectionState.CONNECTED);
      // 不要在对话框中添加连接状态消息
      // addSystemMessage('已连接到服务器');
      
      // 可以在控制台记录连接状态，但不影响UI
      console.log('已连接到服务器  修复cosplay-client里面 webRTC 重复实例化的问题');
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
    
  }, [addUserMessage, addAssistantMessage, addSystemMessage]);
  
  // 连接到服务器
  const connect = useCallback(() => {
    if (clientRef.current && clientRef.current.getConnectionState() === ConnectionState.DISCONNECTED) {
      console.log('[DEBUG] Connecting client');
      clientRef.current.connect();
    }
  }, []);
  
  // 断开连接 - 注意这里不销毁全局实例，只是断开连接
  const disconnect = useCallback(() => {
    if (clientRef.current) {
      console.log('[DEBUG] Disconnecting client (but keeping global instance)');
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
  
  // 添加一个方法来完全清理全局实例，只在需要完全重置时使用
  const resetClient = useCallback(() => {
    console.log('[DEBUG] Completely resetting global client instance');
    if (globalClientInstance) {
      if (isRecording) {
        globalClientInstance.stopListening();
      }
      globalClientInstance.disconnect();
      globalClientInstance = null;
    }
    clientRef.current = null;
    setConnectionState(ConnectionState.DISCONNECTED);
    setIsRecording(false);
  }, [isRecording]);

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
    clearMessages,
    resetClient // 导出这个方法以便在需要时完全重置客户端
  };
}
