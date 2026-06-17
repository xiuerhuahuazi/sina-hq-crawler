"""HTTP 健康检查端点 — 本地 127.0.0.1 返回 JSON 状态。"""

import json
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class _HealthHandler(BaseHTTPRequestHandler):
    """处理 /healthz 请求。"""

    # 共享状态，由 HealthServer.update_status() 更新
    _status: dict[str, Any] = {}
    _lock = threading.Lock()

    def do_GET(self):
        if self.path == "/healthz":
            with self._lock:
                data = dict(self._status)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False, indent=2).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        """静默 HTTP 日志，避免污染采集日志。"""
        pass


class HealthServer:
    """健康检查 HTTP 服务器。端口被占用时回退到文件模式。"""

    def __init__(self, host: str, port: int) -> None:
        self._host = host
        self._port = port
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._file_mode = False
        self._file_path = Path("logs/health.json")

    def start(self) -> bool:
        """启动 HTTP 服务器。成功返回 True，端口被占用回退文件模式返回 False。"""
        try:
            self._server = HTTPServer((self._host, self._port), _HealthHandler)
            self._thread = threading.Thread(
                target=self._server.serve_forever,
                daemon=True,
                name="health-server",
            )
            self._thread.start()
            logger.info("健康检查 HTTP 已启动 http://%s:%d/healthz", self._host, self._port)
            return True
        except OSError as e:
            logger.warning("健康检查 HTTP 端口 %d 不可用 (%s)，回退到文件模式", self._port, e)
            self._file_mode = True
            self._file_path.parent.mkdir(parents=True, exist_ok=True)
            return False

    def stop(self) -> None:
        """停止服务器。"""
        if self._server:
            self._server.shutdown()
            logger.info("健康检查 HTTP 已停止")

    def update_status(self, status: dict) -> None:
        """原子更新状态数据。"""
        if self._file_mode:
            self._write_file(status)
        else:
            with _HealthHandler._lock:
                _HealthHandler._status = status

    def _write_file(self, status: dict) -> None:
        """文件模式：写入 health.json。"""
        try:
            self._file_path.write_text(
                json.dumps(status, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as e:
            logger.debug("写入健康状态文件失败: %s", e)
