import asyncio
import websockets
from config.logger import setup_logging
from core.connection import ConnectionHandler
from core.utils.util import get_local_ip, initialize_modules

TAG = __name__


class WebSocketServer:
    def __init__(self, config: dict, app_context=None):
        self.config = config
        self.app_context = app_context or type('AppContext', (), {'config': config})()
        self.logger = setup_logging()
        modules = initialize_modules(
            self.logger, self.config, True, True, True, True, True, True
        )
        
        # 获取WebRTC模块（如果有）
        self.webrtc_module = getattr(self.app_context, 'webrtc_module', None)
        if self.webrtc_module and self.webrtc_module.is_webrtc_enabled():
            self.logger.bind(tag=TAG).info("WebRTC模块已加载到WebSocket服务器")
        self._vad = modules["vad"]
        self._asr = modules["asr"]
        self._tts = modules["tts"]
        self._llm = modules["llm"]
        self._intent = modules["intent"]
        self._memory = modules["memory"]
        self.active_connections = set()

    async def start(self):
        server_config = self.config["server"]
        host = server_config["ip"]
        port = int(server_config.get("port", 8000))
        
        # 设置WebRTC信令路由（如果启用）
        webrtc_enabled = False
        if self.webrtc_module and self.webrtc_module.is_webrtc_enabled():
            try:
                # 创建aiohttp应用
                from aiohttp import web
                app = web.Application()
                
                # 设置WebRTC信令路由
                await self.webrtc_module.setup_routes(app)
                
                # 启动aiohttp应用（非阻塞）
                webrtc_port = self.config.get('webrtc', {}).get('port', 8082)
                runner = web.AppRunner(app)
                await runner.setup()
                site = web.TCPSite(runner, host, webrtc_port)
                await site.start()
                
                webrtc_enabled = True
                self.logger.bind(tag=TAG).info(
                    f"WebRTC信令服务已启动: ws://{get_local_ip()}:{webrtc_port}{self.webrtc_module.config.signaling_path}"
                )
            except Exception as e:
                self.logger.bind(tag=TAG).error(f"启动WebRTC信令服务失败: {e}")

        self.logger.bind(tag=TAG).info(
            "Server is running at ws://{}:{}/xiaozhi/v1/", get_local_ip(), port
        )
        self.logger.bind(tag=TAG).info(
            "=======上面的地址是websocket协议地址，请勿用浏览器访问======="
        )
        self.logger.bind(tag=TAG).info(
            "如想测试websocket请用谷歌浏览器打开test目录下的test_page.html"
        )
        self.logger.bind(tag=TAG).info(
            "=============================================================\n"
        )
        
        # 如果启用了WebRTC，显示相关信息
        if webrtc_enabled:
            self.logger.bind(tag=TAG).info(
                "WebRTC功能已启用，客户端可以使用WebRTC连接进行音频传输"
            )
            if self.webrtc_module and self.webrtc_module.should_replace_opus():
                self.logger.bind(tag=TAG).info(
                    "WebRTC已配置为替代原有Opus音频处理"
                )
        
        async with websockets.serve(self._handle_connection, host, port):
            await asyncio.Future()

    async def _handle_connection(self, websocket):
        """处理新连接，每次创建独立的ConnectionHandler"""
        # 创建ConnectionHandler时传入当前server实例和app_context
        handler = ConnectionHandler(
            self.config,
            self._vad,
            self._asr,
            self._llm,
            self._tts,
            self._memory,
            self._intent,
            app_context=self.app_context,
        )
        self.active_connections.add(handler)
        try:
            await handler.handle_connection(websocket)
        finally:
            self.active_connections.discard(handler)
