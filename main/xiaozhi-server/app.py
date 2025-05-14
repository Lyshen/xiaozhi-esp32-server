import asyncio
import sys
import signal
import threading
from config.settings import load_config, check_config_file
from core.websocket_server import WebSocketServer
from core.utils.util import check_ffmpeg_installed

# 尝试导入角色API模块
try:
    from role.role_api import register_api
    from flask import Flask
    use_role_api = True
except ImportError:
    use_role_api = False

TAG = __name__


async def wait_for_exit():
    """Windows 和 Linux 兼容的退出监听"""
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    if sys.platform == "win32":
        # Windows: 用 sys.stdin.read() 监听 Ctrl + C
        await loop.run_in_executor(None, sys.stdin.read)
    else:
        # Linux/macOS: 用 signal 监听 Ctrl + C
        def stop():
            stop_event.set()

        loop.add_signal_handler(signal.SIGINT, stop)
        loop.add_signal_handler(signal.SIGTERM, stop)  # 支持 kill 进程
        await stop_event.wait()


# 启动角色管理API服务器的函数
def start_role_api_server(config):
    if not use_role_api:
        print("角色管理API模块未找到，跳过启动API服务器")
        return
    
    try:
        # 创建Flask应用
        app = Flask(__name__)
        # 注册角色API
        register_api(app)
        
        # 获取API服务器端口
        api_port = int(config.get("role_api_port", 8081))
        # 启动API服务器
        print(f"正在启动角色管理API服务器，端口：{api_port}")
        app.run(host='0.0.0.0', port=api_port, debug=False, threaded=True)
    except Exception as e:
        print(f"启动角色管理API服务器失败：{e}")

async def main():
    check_config_file()
    check_ffmpeg_installed()
    config = load_config()
    
    # 启动角色管理API服务器（如果可用）
    if use_role_api:
        role_api_thread = threading.Thread(target=start_role_api_server, args=(config,), daemon=True)
        role_api_thread.start()
        print("角色管理API服务器已在后台启动")

    # 启动 WebSocket 服务器
    ws_server = WebSocketServer(config)
    ws_task = asyncio.create_task(ws_server.start())

    try:
        await wait_for_exit()  # 监听退出信号
    except asyncio.CancelledError:
        print("任务被取消，清理资源中...")
    finally:
        ws_task.cancel()
        try:
            await ws_task
        except asyncio.CancelledError:
            pass
        print("服务器已关闭，程序退出。")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("手动中断，程序终止。")
