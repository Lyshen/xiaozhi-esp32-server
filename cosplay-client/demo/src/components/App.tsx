import React from 'react';
import ConnectionStatus from './ConnectionStatus';
import ConversationView from './ConversationView';
import AudioControls from './AudioControls';
import MessageInput from './MessageInput';
import { useCosplayClient } from '../hooks/useCosplayClient';
import { ConnectionState } from 'cosplay-client';
import '../styles/App.css';

const App: React.FC = () => {
  const {
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
  } = useCosplayClient({
    serverUrl: 'ws://localhost:8001/xiaozhi/v1/', // 连接到服务器的WebSocket端点
    autoConnect: true // 自动连接
  });

  const isConnected = connectionState === ConnectionState.CONNECTED;

  return (
    <div className="app-container">
      <header className="app-header">
        <h1>Cosplay Client Demo</h1>
        <ConnectionStatus 
          connectionState={connectionState}
          onConnect={connect}
          onDisconnect={disconnect}
        />
      </header>

      <main className="app-main">
        <ConversationView 
          messages={messages}
          onClear={clearMessages}
        />
      </main>

      <footer className="app-footer">
        <AudioControls 
          isRecording={isRecording}
          isContinuousMode={isContinuousMode}
          isConnected={isConnected}
          onStartRecording={startRecording}
          onStopRecording={stopRecording}
          onToggleContinuousMode={toggleContinuousMode}
        />
        <MessageInput 
          onSendMessage={sendTextMessage}
          isConnected={isConnected}
        />
      </footer>

      <div className="app-info">
        <p>已连接到: {isConnected ? 'ws://localhost:8001/xiaozhi/v1/' : '未连接'}</p>
        <p>
          <small>
            {isConnected ? '请尝试录音或发送文本消息与服务器交互' : '请先连接到服务器'}
          </small>
        </p>
      </div>
    </div>
  );
};

export default App;
