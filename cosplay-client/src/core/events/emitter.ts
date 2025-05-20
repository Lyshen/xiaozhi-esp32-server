/**
 * 简单的事件发射器实现
 * 负责处理组件间的事件通信
 */
export class EventEmitter {
  private events: Map<string, Function[]> = new Map();

  /**
   * 注册事件监听器
   * @param event 事件名称
   * @param listener 事件监听函数
   */
  public on(event: string, listener: Function): void {
    if (!this.events.has(event)) {
      this.events.set(event, []);
    }
    
    const listeners = this.events.get(event);
    if (listeners) {
      listeners.push(listener);
    }
  }

  /**
   * 注册一次性事件监听器
   * @param event 事件名称
   * @param listener 事件监听函数
   */
  public once(event: string, listener: Function): void {
    const onceWrapper = (...args: any[]) => {
      listener(...args);
      this.off(event, onceWrapper);
    };
    
    this.on(event, onceWrapper);
  }

  /**
   * 移除事件监听器
   * @param event 事件名称
   * @param listener 要移除的监听函数
   */
  public off(event: string, listener: Function): void {
    if (!this.events.has(event)) {
      return;
    }
    
    const listeners = this.events.get(event);
    if (listeners) {
      const index = listeners.indexOf(listener);
      if (index !== -1) {
        listeners.splice(index, 1);
      }
      
      // 如果没有监听器了，则删除整个事件
      if (listeners.length === 0) {
        this.events.delete(event);
      }
    }
  }

  /**
   * 发射事件
   * @param event 事件名称
   * @param args 事件参数
   */
  public emit(event: string, ...args: any[]): void {
    if (!this.events.has(event)) {
      return;
    }
    
    const listeners = this.events.get(event);
    if (listeners) {
      // 创建副本以防在回调中修改了监听器数组
      [...listeners].forEach(listener => {
        try {
          listener(...args);
        } catch (error) {
          console.error(`Error in event listener for "${event}":`, error);
        }
      });
    }
  }

  /**
   * 移除所有事件监听器
   * @param event 可选的事件名称，如果提供，只移除该事件的所有监听器
   */
  public removeAllListeners(event?: string): void {
    if (event) {
      this.events.delete(event);
    } else {
      this.events.clear();
    }
  }
}
