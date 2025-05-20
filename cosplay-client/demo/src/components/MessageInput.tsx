import React, { useState } from 'react';
import '../styles/MessageInput.css';

interface MessageInputProps {
  onSendMessage: (text: string) => void;
  isConnected: boolean;
}

const MessageInput: React.FC<MessageInputProps> = ({ onSendMessage, isConnected }) => {
  const [message, setMessage] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (message.trim() && isConnected) {
      onSendMessage(message);
      setMessage('');
    }
  };

  return (
    <form className="message-input-form" onSubmit={handleSubmit}>
      <input
        type="text"
        placeholder={isConnected ? "输入消息..." : "请先连接服务器..."}
        value={message}
        onChange={(e) => setMessage(e.target.value)}
        disabled={!isConnected}
        className="message-input"
      />
      <button 
        type="submit" 
        disabled={!isConnected || !message.trim()}
        className="send-button"
      >
        发送
      </button>
    </form>
  );
};

export default MessageInput;
