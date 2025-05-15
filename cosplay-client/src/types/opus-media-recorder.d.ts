declare module 'opus-media-recorder' {
  export default class MediaRecorder {
    constructor(stream: MediaStream, options?: MediaRecorderOptions);
    
    static isTypeSupported(mimeType: string): boolean;
    
    start(timeslice?: number): void;
    stop(): void;
    pause(): void;
    resume(): void;
    
    ondataavailable: (event: { data: Blob }) => void;
    onstop: () => void;
    onerror: (event: ErrorEvent) => void;
    
    state: 'inactive' | 'recording' | 'paused';
    stream: MediaStream;
    mimeType: string;
  }
  
  export interface MediaRecorderOptions {
    mimeType?: string;
    audioBitsPerSecond?: number;
    videoBitsPerSecond?: number;
    bitsPerSecond?: number;
    audioChannels?: number;
    audioBitrateMode?: number;
  }
}
