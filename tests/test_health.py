"""Tests for src/health.py — HTTP 健康检查端点。"""

import json
import socket
import threading
import time
import urllib.request

import pytest

from src.health import HealthServer, _HealthHandler


class TestHealthServer:
    """HealthServer 测试。"""

    def _get_free_port(self):
        """获取一个可用端口。"""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    def test_start_and_get_healthz(self):
        """正常启动 + GET /healthz 返回 200 JSON。"""
        port = self._get_free_port()
        server = HealthServer("127.0.0.1", port)
        try:
            result = server.start()
            assert result is True

            server.update_status({"status": "running", "uptime": 100})

            resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz")
            data = json.loads(resp.read())
            assert data["status"] == "running"
            assert data["uptime"] == 100
        finally:
            server.stop()

    def test_unknown_path_returns_404(self):
        """GET /unknown → 404。"""
        port = self._get_free_port()
        server = HealthServer("127.0.0.1", port)
        try:
            server.start()
            with pytest.raises(urllib.error.HTTPError) as exc_info:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/unknown")
            assert exc_info.value.code == 404
        finally:
            server.stop()

    def test_update_status_reflects(self):
        """update_status 后 GET 反映新状态。"""
        port = self._get_free_port()
        server = HealthServer("127.0.0.1", port)
        try:
            server.start()
            server.update_status({"status": "sleeping"})
            resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz")
            data = json.loads(resp.read())
            assert data["status"] == "sleeping"
        finally:
            server.stop()

    def test_port_in_use_fallback_to_file(self, tmp_path):
        """端口被占用 → 回退到文件模式。"""
        # 占用一个端口
        port = self._get_free_port()
        blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        blocker.bind(("127.0.0.1", port))
        blocker.listen(1)

        try:
            server = HealthServer("127.0.0.1", port)
            server._file_path = tmp_path / "health.json"
            result = server.start()
            assert result is False  # 回退到文件模式

            server.update_status({"status": "running"})
            assert server._file_path.exists()
            data = json.loads(server._file_path.read_text(encoding="utf-8"))
            assert data["status"] == "running"
        finally:
            blocker.close()

    def test_stop(self):
        """stop 后服务器不再响应。"""
        port = self._get_free_port()
        server = HealthServer("127.0.0.1", port)
        server.start()
        server.stop()
        # 服务器已停止，连接应失败
        with pytest.raises(Exception):
            urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=1)

    def test_start_returns_true_on_success(self):
        """成功启动返回 True。"""
        port = self._get_free_port()
        server = HealthServer("127.0.0.1", port)
        try:
            assert server.start() is True
        finally:
            server.stop()


class TestHealthHandler:
    """_HealthHandler 底层测试。"""

    def test_handler_has_default_status(self):
        """Handler 初始状态为空 dict。"""
        # 清除可能残留的状态
        with _HealthHandler._lock:
            _HealthHandler._status = {}
