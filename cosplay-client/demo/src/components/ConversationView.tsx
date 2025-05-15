import React, { useRef, useEffect } from 'react';
import '../styles/ConversationView.css';

interface Message {
  id: string;
  text: string;
  isUser: boolean;
  timestamp: number;
}

interface ConversationViewProps {
  messages: Message[];
  onClear: () => void;
}

const ConversationView: React.FC<ConversationViewProps> = ({ messages, onClear }) => {
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // 自动滚动到最新消息
  useEffect(() => {
    if (messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages]);

  // 格式化时间戳
  const formatTime = (timestamp: number) => {
    const date = new Date(timestamp);
    return `${date.getHours().toString().padStart(2, '0')}:${date.getMinutes().toString().padStart(2, '0')}`;
  };

  return (
    <div className="conversation-container">
      <div className="conversation-header">
        <h2>对话历史</h2>
        {messages.length > 0 && (
          <button className="clear-button" onClick={onClear}>
            清空
          </button>
        )}
      </div>
      <div className="messages-container">
        {messages.length === 0 ? (
          <div className="empty-state">
            <p>没有消息历史</p>
            <p>开始录音或发送消息来开始对话</p>
          </div>
        ) : (
          messages.map(message => (
            <div 
              key={message.id} 
              className={`message ${message.isUser ? 'user-message' : 'assistant-message'}`}
            >
              <div className="message-content">{message.text}</div>
              <div className="message-time">{formatTime(message.timestamp)}</div>
            </div>
          ))
        )}
        <div ref={messagesEndRef} />
      </div>
    </div>
  );
};

export default ConversationView;
