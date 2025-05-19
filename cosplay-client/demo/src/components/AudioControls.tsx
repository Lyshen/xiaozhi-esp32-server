import React, { useState, useEffect, useRef } from 'react';
import '../styles/AudioControls.css';

// 定义三种录音模式：按住说话、点击开始/停止、连续录音
const RecordingMode = {
  PUSH_TO_TALK: 'push_to_talk',
  TOGGLE: 'toggle',
  CONTINUOUS: 'continuous'
} as const;

type RecordingModeType = typeof RecordingMode[keyof typeof RecordingMode];

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
  // 当前录音模式
  const [recordingMode, setRecordingMode] = useState<RecordingModeType>(
    RecordingMode.PUSH_TO_TALK
  );
  
  // 按下状态跟踪（用于按住说话模式）
  const [isPressHolding, setIsPressHolding] = useState(false);
  
  // 按钮引用，用于移动端长按事件
  const pushToTalkRef = useRef<HTMLButtonElement>(null);
  
  // 长按定时器
  const longPressTimer = useRef<number | null>(null);
  
  // 是否正在显示ripple效果
  const [showRipple, setShowRipple] = useState(false);
  const rippleTimeoutRef = useRef<number | null>(null);
  
  // 监听模式变化
  useEffect(() => {
    if (isContinuousMode) {
      setRecordingMode(RecordingMode.CONTINUOUS);
    } else {
      // 默认使用按住说话模式
      setRecordingMode(RecordingMode.PUSH_TO_TALK);
    }
  }, [isContinuousMode]);
  
  // 清理定时器
  useEffect(() => {
    return () => {
      if (longPressTimer.current) {
        clearTimeout(longPressTimer.current);
      }
      if (rippleTimeoutRef.current) {
        clearTimeout(rippleTimeoutRef.current);
      }
    };
  }, []);
  
  // 按住说话模式的处理函数
  const handlePushToTalkStart = (event: React.MouseEvent | React.TouchEvent) => {
    event.preventDefault();
    if (!isConnected) return;
    
    // 开始录音
    onStartRecording();
    setIsPressHolding(true);
    
    // 显示涟漪效果
    setShowRipple(true);
    if (rippleTimeoutRef.current) {
      clearTimeout(rippleTimeoutRef.current);
    }
  };
  
  const handlePushToTalkEnd = (event: React.MouseEvent | React.TouchEvent) => {
    event.preventDefault();
    if (!isPressHolding) return;
    
    // 结束录音
    onStopRecording();
    setIsPressHolding(false);
    
    // 淡出涟漪效果
    rippleTimeoutRef.current = window.setTimeout(() => {
      setShowRipple(false);
    }, 300);
  };
  
  // 点击模式切换
  const handleModeToggle = () => {
    const newMode = recordingMode === RecordingMode.PUSH_TO_TALK ? 
      RecordingMode.TOGGLE : RecordingMode.PUSH_TO_TALK;
      
    setRecordingMode(newMode);
  };
  
  // 切换录音（用于点击模式）
  const handleToggleRecording = () => {
    if (!isConnected) return;
    
    if (isRecording) {
      onStopRecording();
    } else {
      onStartRecording();
    }
  };
  
  // 渲染不同的按钮基于当前模式
  const renderRecordingButton = () => {
    if (isContinuousMode) {
      return (
        <div className="continuous-mode-active">
          <div className="pulse-circle continuous"></div>
          <span>持续录音已启用</span>
        </div>
      );
    }
    
    if (recordingMode === RecordingMode.PUSH_TO_TALK) {
      return (
        <button 
          ref={pushToTalkRef}
          className={`push-to-talk-button ${isPressHolding ? 'active' : ''} ${showRipple ? 'ripple' : ''}`}
          onMouseDown={handlePushToTalkStart}
          onMouseUp={handlePushToTalkEnd}
          onMouseLeave={handlePushToTalkEnd}
          onTouchStart={handlePushToTalkStart}
          onTouchEnd={handlePushToTalkEnd}
          onTouchCancel={handlePushToTalkEnd}
          disabled={!isConnected}
          title={isConnected ? '按住说话' : '请先连接服务器'}
        >
          <div className="mic-icon">🎤</div>
          <span>按住说话</span>
          {showRipple && <span className="ripple-effect"></span>}
        </button>
      );
    }
    
    return (
      <button 
        className={`record-button ${isRecording ? 'recording' : ''}`}
        onClick={handleToggleRecording}
        disabled={!isConnected}
        title={isConnected ? (isRecording ? '停止录音' : '开始录音') : '请先连接服务器'}
      >
        <div className="record-icon">
          {isRecording ? '■' : '●'}
        </div>
        <span>{isRecording ? '停止' : '录音'}</span>
      </button>
    );
  };

  return (
    <div className="audio-controls">
      <div className="recording-status">
        {(isRecording || isPressHolding) && (
          <div className="recording-indicator">
            <div className="pulse-circle"></div>
            <span>{isPressHolding ? '正在聆听...' : '录音中...'}</span>
          </div>
        )}
      </div>
      
      <div className="controls-container">
        {renderRecordingButton()}
        
        <div className="mode-toggles">
          {!isContinuousMode && (
            <button 
              className={`mode-toggle-button ${recordingMode === RecordingMode.PUSH_TO_TALK ? 'active' : ''}`}
              onClick={handleModeToggle}
              disabled={!isConnected || isRecording}
              title="切换录音模式"
            >
              <span>{recordingMode === RecordingMode.PUSH_TO_TALK ? '按住模式' : '点击模式'}</span>
            </button>
          )}
          
          <label className="continuous-mode-toggle">
            <input 
              type="checkbox" 
              checked={isContinuousMode} 
              onChange={onToggleContinuousMode}
              disabled={!isConnected || isRecording || isPressHolding}
            />
            <span className="toggle-label">持续录音</span>
          </label>
        </div>
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
