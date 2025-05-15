import React from 'react';
import { ConnectionState } from 'cosplay-client';
import '../styles/ConnectionStatus.css';

interface ConnectionStatusProps {
  connectionState: ConnectionState;
  onConnect: () => void;
  onDisconnect: () => void;
}

const ConnectionStatus: React.FC<ConnectionStatusProps> = ({ 
  connectionState, 
  onConnect, 
  onDisconnect 
}) => {
  return (
    <div className="connection-status">
      <div className="status-indicator">
        <div 
          className={`status-dot ${connectionState === ConnectionState.CONNECTED ? 'connected' : 'disconnected'}`} 
        />
        <span className="status-text">
          {connectionState === ConnectionState.CONNECTED && '已连接'}
          {connectionState === ConnectionState.CONNECTING && '连接中...'}
          {connectionState === ConnectionState.DISCONNECTED && '未连接'}
          {connectionState === ConnectionState.RECONNECTING && '重新连接中...'}
          {connectionState === ConnectionState.ERROR && '连接错误'}
        </span>
      </div>
      <div className="status-actions">
        {connectionState === ConnectionState.DISCONNECTED && (
          <button 
            className="connect-button"
            onClick={onConnect}
          >
            连接
          </button>
        )}
        {(connectionState === ConnectionState.CONNECTED || 
          connectionState === ConnectionState.RECONNECTING) && (
          <button 
            className="disconnect-button"
            onClick={onDisconnect}
          >
            断开
          </button>
        )}
      </div>
    </div>
  );
};

export default ConnectionStatus;
