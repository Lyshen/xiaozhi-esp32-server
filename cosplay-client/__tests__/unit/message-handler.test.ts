import { MessageHandler } from '../../src/core/protocol/handlers';
import { ClientEvent, MessageType } from '../../src/types';
import { EventEmitter } from 'events';

describe('MessageHandler', () => {
  let messageHandler: MessageHandler;
  let eventEmitter: EventEmitter;
  
  beforeEach(() => {
    eventEmitter = new EventEmitter();
    messageHandler = new MessageHandler(eventEmitter);
  });
  
  test('should handle hello message correctly', () => {
    // 创建一个监听hello事件的mock函数
    const mockListener = jest.fn();
    eventEmitter.on(ClientEvent.CONNECTED, mockListener); // 使用CONNECTED事件代替HELLO
    
    // 创建一个模拟的hello消息
    const helloMessage = {
      type: MessageType.HELLO,
      version: 1,
      transport: 'websocket',
      session_id: 'test-session-123',
      audio_params: {
        format: 'pcm',
        sample_rate: 16000,
        channels: 1,
        frame_duration: 20
      }
    };
    
    // 处理消息
    messageHandler.handleMessage(JSON.stringify(helloMessage));
    
    // 验证事件是否被正确触发
    expect(mockListener).toHaveBeenCalledWith(helloMessage);
    
    // 验证session_id是否被正确设置
    expect(messageHandler.getSessionId()).toBe('test-session-123');
  });
  
  test('should handle STT message correctly', () => {
    // 创建一个监听STT事件的mock函数
    const mockListener = jest.fn();
    eventEmitter.on(ClientEvent.SPEECH_RECOGNITION, mockListener); // 使用SPEECH_RECOGNITION事件
    
    // 创建一个模拟的STT消息
    const sttMessage = {
      type: MessageType.STT,
      text: 'Hello, this is a test',
      final: true
    };
    
    // 处理消息
    messageHandler.handleMessage(JSON.stringify(sttMessage));
    
    // 验证事件是否被正确触发
    expect(mockListener).toHaveBeenCalledWith(sttMessage);
  });
  
  test('should handle TTS status message correctly', () => {
    // 创建一个监听TTS状态事件的mock函数
    const mockListener = jest.fn();
    eventEmitter.on(ClientEvent.AUDIO_PLAY_END, mockListener); // 使用AUDIO_PLAY_END事件
    
    // 创建一个模拟的TTS状态消息
    const ttsStatusMessage = {
      type: MessageType.TTS, // 使用TTS而非TTS_STATUS
      status: 'completed',
      request_id: 'tts-request-123'
    };
    
    // 处理消息
    messageHandler.handleMessage(JSON.stringify(ttsStatusMessage));
    
    // 验证事件是否被正确触发
    expect(mockListener).toHaveBeenCalledWith(ttsStatusMessage);
  });
  
  test('should emit error for invalid JSON', () => {
    // 创建一个监听错误事件的mock函数
    const mockListener = jest.fn();
    eventEmitter.on(ClientEvent.ERROR, mockListener);
    
    // 处理无效的JSON
    messageHandler.handleMessage('This is not valid JSON');
    
    // 验证错误事件是否被触发
    expect(mockListener).toHaveBeenCalled();
    expect(mockListener.mock.calls[0][0]).toContain('Error parsing message');
  });
  
  test('should emit error for unknown message type', () => {
    // 创建一个监听错误事件的mock函数
    const mockListener = jest.fn();
    eventEmitter.on(ClientEvent.ERROR, mockListener);
    
    // 处理未知类型的消息
    messageHandler.handleMessage(JSON.stringify({
      type: 'UNKNOWN_TYPE',
      data: 'some data'
    }));
    
    // 验证错误事件是否被触发
    expect(mockListener).toHaveBeenCalled();
    expect(mockListener.mock.calls[0][0]).toContain('Unknown message type');
  });
  
  test('should handle binary audio data', () => {
    // 创建一个监听音频数据事件的mock函数
    const mockListener = jest.fn();
    eventEmitter.on(ClientEvent.AUDIO_PLAY_START, mockListener); // 使用AUDIO_PLAY_START事件
    
    // 创建模拟的二进制音频数据
    const audioData = new ArrayBuffer(1024);
    
    // 处理二进制数据
    messageHandler.handleMessage(audioData);
    
    // 验证音频数据事件是否被触发
    expect(mockListener).toHaveBeenCalledWith(audioData);
  });
});
