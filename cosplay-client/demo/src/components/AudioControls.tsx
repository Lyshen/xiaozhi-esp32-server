import React from 'react';
import '../styles/AudioControls.css';

interface AudioControlsProps {
  isRecording: boolean;
  isContinuousMode: boolean;
  isConnected: boolean;
  onStartRecording: () => void;
  onStopRecording: () => void;
  onToggleContinuousMode: () => void;
}

const AudioControls: React.FC<AudioControlsProps> = ({
  isRecording,
  isContinuousMode,
  isConnected,
  onStartRecording,
  onStopRecording,
  onToggleContinuousMode,
}) => {
  return (
    <div className="audio-controls">
      <div className="recording-status">
        {isRecording && (
          <div className="recording-indicator">
            <div className="pulse-circle"></div>
            <span>录音中...</span>
          </div>
        )}
      </div>
      
      <div className="controls-container">
        {!isContinuousMode && (
          <button 
            className={`record-button ${isRecording ? 'recording' : ''}`}
            onClick={isRecording ? onStopRecording : onStartRecording}
            disabled={!isConnected}
            title={isConnected ? (isRecording ? '停止录音' : '开始录音') : '请先连接服务器'}
          >
            <div className="record-icon">
              {isRecording ? '■' : '●'}
            </div>
            <span>{isRecording ? '停止' : '录音'}</span>
          </button>
        )}
        
        <label className="continuous-mode-toggle">
          <input 
            type="checkbox" 
            checked={isContinuousMode} 
            onChange={onToggleContinuousMode}
            disabled={!isConnected || isRecording}
          />
          <span className="toggle-label">持续录音模式</span>
        </label>
        
        {isContinuousMode && isConnected && (
          <div className="continuous-mode-active">
            <div className="pulse-circle continuous"></div>
            <span>持续录音已启用</span>
          </div>
        )}
      </div>
      
      {!isConnected && (
        <div className="connection-warning">
          请先连接到服务器
        </div>
      )}
    </div>
  );
};

export default AudioControls;
