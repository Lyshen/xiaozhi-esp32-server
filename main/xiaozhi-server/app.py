import asyncio
import sys
import signal
import threading
import traceback
from config.settings import load_config, check_config_file
from core.websocket_server import WebSocketServer
from core.utils.util import check_ffmpeg_installed
from config.logger import setup_logging

# 设置日志记录器
logger = setup_logging()
TAG = __name__
logger = logger.bind(tag=TAG)

# 尝试导入简单角色API服务器模块
try:
    from role.simple_role_server import start_server_in_thread
    use_role_api = True
    logger.info("成功导入简单角色API服务器模块")
except ImportError as e:
    use_role_api = False
    logger.error(f"导入简单角色API服务器模块失败: {e}")



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
        logger.warning("角色管理API模块未找到，跳过启动API服务器")
        return
    
    try:
        # 获取API服务器端口
        api_port = int(config.get("role_api_port", 8081))
        # 使用简单角色API服务器启动
        logger.info(f"正在启动简单角色管理API服务器，端口：{api_port}")
        start_server_in_thread(port=api_port)
        logger.info(f"简单角色管理API服务器已启动，可通过http://localhost:{api_port}/api/roles访问")
    except Exception as e:
        error_trace = traceback.format_exc()
        logger.error(f"启动简单角色管理API服务器失败：{e}\n{error_trace}")

async def main():
    check_config_file()
    check_ffmpeg_installed()
    config = load_config()
    
    # 启动角色管理API服务器（如果可用）
    if use_role_api:
        try:
            logger.info("直接启动简单角色管理API服务器")
            # 直接调用启动函数，不需要创建新线程
            start_role_api_server(config)
            # 等待一小段时间确认启动成功
            await asyncio.sleep(1)
            logger.info("简单角色管理API服务器启动完成")
        except Exception as e:
            error_trace = traceback.format_exc()
            logger.error(f"启动简单角色管理API服务器失败: {e}\n{error_trace}")

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
        logger.info("程序启动中...")
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("手动中断，程序终止。")
    except Exception as e:
        error_trace = traceback.format_exc()
        logger.error(f"程序运行出错: {e}\n{error_trace}")
