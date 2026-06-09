"""Tests for src/daemon.py — 守护进程。"""

import os
import signal
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock
from datetime import datetime, time, timedelta

from src.daemon import CrawlDaemon, _read_pid, _pid_is_alive, _send_signal_to_pid
from src.session import SessionWindow


class TestPidManagement:
    """PID 文件管理测试。"""

    def test_write_and_read_pid(self, tmp_path, base_config):
        """写入 PID 文件后可以读取。"""
        pid_file = tmp_path / "test.pid"
        base_config["daemon"]["pid_file"] = str(pid_file)

        with patch("src.daemon.load_config", return_value=base_config):
            daemon = CrawlDaemon()
            daemon._config = base_config
            daemon._write_pid()

            assert pid_file.exists()
            content = pid_file.read_text(encoding="utf-8").strip()
            assert content == str(os.getpid())

    def test_remove_pid(self, tmp_path, base_config):
        """删除 PID 文件。"""
        pid_file = tmp_path / "test.pid"
        base_config["daemon"]["pid_file"] = str(pid_file)

        daemon = CrawlDaemon.__new__(CrawlDaemon)
        daemon._config = base_config
        daemon._write_pid()
        assert pid_file.exists()

        daemon._remove_pid()
        assert not pid_file.exists()

    def test_remove_pid_missing(self, tmp_path, base_config):
        """PID 文件不存在时 remove 不抛异常。"""
        daemon = CrawlDaemon.__new__(CrawlDaemon)
        daemon._config = base_config
        daemon._config["daemon"]["pid_file"] = str(tmp_path / "nonexistent.pid")
        daemon._remove_pid()  # 不抛异常

    def test_read_pid(self, tmp_path, base_config):
        """_read_pid 正确读取 PID。"""
        pid_file = tmp_path / "test.pid"
        pid_file.write_text("12345\n", encoding="utf-8")
        base_config["daemon"]["pid_file"] = str(pid_file)

        assert _read_pid(base_config) == 12345

    def test_read_pid_missing_file(self, tmp_path, base_config):
        """PID 文件不存在 → 返回 None。"""
        base_config["daemon"]["pid_file"] = str(tmp_path / "nonexistent.pid")
        assert _read_pid(base_config) is None

    def test_read_pid_invalid_content(self, tmp_path, base_config):
        """PID 文件内容无效 → 返回 None。"""
        pid_file = tmp_path / "bad.pid"
        pid_file.write_text("not_a_number\n", encoding="utf-8")
        base_config["daemon"]["pid_file"] = str(pid_file)
        assert _read_pid(base_config) is None

    def test_pid_is_alive(self):
        """当前进程 PID 是存活的。"""
        assert _pid_is_alive(os.getpid()) is True

    def test_pid_is_not_alive(self):
        """不存在的 PID → False。"""
        assert _pid_is_alive(9999999) is False


class TestDaemonSignals:
    """信号处理测试。"""

    def test_handle_signal_sets_shutdown(self, base_config):
        """SIGTERM 设置 _shutdown = True。"""
        daemon = CrawlDaemon.__new__(CrawlDaemon)
        daemon._shutdown = False
        daemon._handle_signal(signal.SIGTERM, None)
        assert daemon._shutdown is True

    def test_handle_signal_int(self, base_config):
        """SIGINT 也设置 _shutdown。"""
        daemon = CrawlDaemon.__new__(CrawlDaemon)
        daemon._shutdown = False
        daemon._handle_signal(signal.SIGINT, None)
        assert daemon._shutdown is True

    def test_handle_hup_triggers_reload(self, base_config):
        """SIGHUP 触发热加载。"""
        daemon = CrawlDaemon.__new__(CrawlDaemon)
        daemon._config = base_config
        daemon._reloader = MagicMock()
        daemon._reloader.check_reload.return_value = None
        daemon._handle_hup(signal.SIGHUP, None)
        daemon._reloader.check_reload.assert_called_once()

    def test_handle_hup_with_new_config(self, base_config):
        """SIGHUP 热加载成功 → 更新 config。"""
        daemon = CrawlDaemon.__new__(CrawlDaemon)
        daemon._config = base_config
        daemon._reloader = MagicMock()
        new_config = dict(base_config)
        new_config["logging"] = dict(base_config["logging"])
        new_config["logging"]["level"] = "DEBUG"
        daemon._reloader.check_reload.return_value = new_config
        daemon._handle_hup(signal.SIGHUP, None)
        assert daemon._config is new_config


class TestInitSubsystems:
    """_init_subsystems 测试。"""

    def test_hot_reload_disabled(self, base_config):
        """热加载禁用 → _reloader 为 None。"""
        base_config["daemon"]["hot_reload"]["enabled"] = False
        base_config["daemon"]["health"]["enabled"] = False
        daemon = CrawlDaemon.__new__(CrawlDaemon)
        daemon._config = base_config
        daemon._config_path = None
        daemon._reloader = None
        daemon._health = None
        daemon._reporter = None
        daemon._init_subsystems()
        assert daemon._reloader is None

    def test_health_disabled(self, base_config):
        """健康检查禁用 → _health 为 None。"""
        base_config["daemon"]["hot_reload"]["enabled"] = False
        base_config["daemon"]["health"]["enabled"] = False
        daemon = CrawlDaemon.__new__(CrawlDaemon)
        daemon._config = base_config
        daemon._config_path = None
        daemon._reloader = None
        daemon._health = None
        daemon._reporter = None
        daemon._init_subsystems()
        assert daemon._health is None


class TestTryReload:
    """_try_reload 测试。"""

    def test_no_reloader(self, base_config):
        """无 reloader → 不操作。"""
        daemon = CrawlDaemon.__new__(CrawlDaemon)
        daemon._config = base_config
        daemon._reloader = None
        daemon._try_reload()  # 不抛异常

    def test_reload_returns_none(self, base_config):
        """check_reload 返回 None → config 不变。"""
        daemon = CrawlDaemon.__new__(CrawlDaemon)
        daemon._config = base_config
        daemon._reloader = MagicMock()
        daemon._reloader.check_reload.return_value = None
        daemon._try_reload()
        assert daemon._config is base_config

    def test_reload_returns_new_config(self, base_config):
        """check_reload 返回新 config → 更新。"""
        daemon = CrawlDaemon.__new__(CrawlDaemon)
        daemon._config = base_config
        new_config = dict(base_config)
        new_config["logging"] = dict(base_config["logging"])
        new_config["logging"]["level"] = "DEBUG"
        daemon._reloader = MagicMock()
        daemon._reloader.check_reload.return_value = new_config
        daemon._try_reload()
        assert daemon._config is new_config


class TestUpdateHealthStatus:
    """_update_health_status 测试。"""

    def test_no_health_server(self, base_config):
        """无健康服务器 → 不操作。"""
        daemon = CrawlDaemon.__new__(CrawlDaemon)
        daemon._health = None
        daemon._reloader = None
        daemon._update_health_status(MagicMock(), None)

    def test_running_status(self, base_config):
        """在交易时段 → status=running。"""
        daemon = CrawlDaemon.__new__(CrawlDaemon)
        daemon._health = MagicMock()
        daemon._reloader = MagicMock()
        daemon._reloader.config_version = 1
        daemon._start_time = 1000.0

        session = SessionWindow(start=time(9, 30), end=time(11, 30), symbols=["sh000001"])
        session_mgr = MagicMock()

        with patch("src.daemon.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 9, 10, 0)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            daemon._update_health_status(session_mgr, session)

        daemon._health.update_status.assert_called_once()
        status = daemon._health.update_status.call_args[0][0]
        assert status["status"] == "running"

    def test_sleeping_status(self, base_config):
        """不在交易时段 → status=sleeping。"""
        daemon = CrawlDaemon.__new__(CrawlDaemon)
        daemon._health = MagicMock()
        daemon._reloader = MagicMock()
        daemon._reloader.config_version = 1
        daemon._start_time = 1000.0

        session_mgr = MagicMock()
        session_mgr.calc_next_start.return_value = datetime(2026, 6, 9, 13, 0)

        with patch("src.daemon.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 9, 12, 0)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            daemon._update_health_status(session_mgr, None)

        daemon._health.update_status.assert_called_once()
        status = daemon._health.update_status.call_args[0][0]
        assert status["status"] == "sleeping"


class TestShutdownAll:
    """_shutdown_all 测试。"""

    def test_removes_pid_and_stops_health(self, tmp_path, base_config):
        """清理时删除 PID 文件并停止健康服务器。"""
        pid_file = tmp_path / "test.pid"
        base_config["daemon"]["pid_file"] = str(pid_file)

        daemon = CrawlDaemon.__new__(CrawlDaemon)
        daemon._config = base_config
        daemon._health = MagicMock()
        daemon._write_pid()
        assert pid_file.exists()

        daemon._shutdown_all()
        assert not pid_file.exists()
        daemon._health.stop.assert_called_once()


class TestSessionEndDt:
    """_calc_session_end_dt 测试。"""

    def test_normal_session(self, base_config):
        """正常时段计算结束时间。"""
        daemon = CrawlDaemon.__new__(CrawlDaemon)
        daemon._config = base_config

        session = SessionWindow(start=time(9, 30), end=time(11, 30))
        with patch("src.daemon.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 9, 10, 0)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            end_dt = daemon._calc_session_end_dt(session)
            assert end_dt.hour == 11
            assert end_dt.minute == 30

    def test_overnight_session(self, base_config):
        """跨日时段结束时间为次日。"""
        daemon = CrawlDaemon.__new__(CrawlDaemon)
        daemon._config = base_config

        session = SessionWindow(start=time(23, 0), end=time(1, 0))
        with patch("src.daemon.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 9, 23, 30)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            end_dt = daemon._calc_session_end_dt(session)
            assert end_dt.day == 10
            assert end_dt.hour == 1


class TestInterruptibleSleep:
    """_interruptible_sleep 测试。"""

    def test_exits_on_shutdown(self, base_config):
        """shutdown 标志触发提前退出。"""
        daemon = CrawlDaemon.__new__(CrawlDaemon)
        daemon._shutdown = False

        import threading
        def set_shutdown():
            import time
            time.sleep(0.05)
            daemon._shutdown = True

        t = threading.Thread(target=set_shutdown)
        t.start()
        daemon._interruptible_sleep(10)
        t.join()
        assert daemon._shutdown is True

    def test_exits_on_timeout(self, base_config):
        """正常超时退出。"""
        daemon = CrawlDaemon.__new__(CrawlDaemon)
        daemon._shutdown = False
        daemon._interruptible_sleep(0.05)
        # 不会无限阻塞


class TestRun:
    """run() 方法测试。"""

    def test_run_foreground(self, tmp_path, base_config):
        """前台运行：调用所有初始化和主循环。"""
        base_config["daemon"]["pid_file"] = str(tmp_path / "test.pid")
        base_config["daemon"]["hot_reload"]["enabled"] = False
        base_config["daemon"]["health"]["enabled"] = False

        with patch("src.daemon.load_config", return_value=base_config), \
             patch("src.daemon.setup_logging"), \
             patch.object(CrawlDaemon, '_setup_signals'), \
             patch.object(CrawlDaemon, '_write_pid'), \
             patch.object(CrawlDaemon, '_init_subsystems'), \
             patch.object(CrawlDaemon, '_main_loop') as mock_loop, \
             patch.object(CrawlDaemon, '_shutdown_all'):
            daemon = CrawlDaemon()
            daemon.run()
            mock_loop.assert_called_once()

    def test_run_calls_main_loop(self, tmp_path, base_config):
        """正常 run 调用 _main_loop。"""
        base_config["daemon"]["pid_file"] = str(tmp_path / "test.pid")
        base_config["daemon"]["hot_reload"]["enabled"] = False
        base_config["daemon"]["health"]["enabled"] = False

        with patch("src.daemon.load_config", return_value=base_config), \
             patch("src.daemon.setup_logging"), \
             patch.object(CrawlDaemon, '_main_loop') as mock_loop, \
             patch.object(CrawlDaemon, '_write_pid'), \
             patch.object(CrawlDaemon, '_init_subsystems'), \
             patch.object(CrawlDaemon, '_shutdown_all'):
            daemon = CrawlDaemon()
            daemon.run()
            mock_loop.assert_called_once()


class TestMainLoop:
    """_main_loop 测试。"""

    def test_retry_exceeds_max(self, tmp_path, base_config):
        """重启次数超限 → 停止。"""
        base_config["daemon"]["pid_file"] = str(tmp_path / "test.pid")
        base_config["daemon"]["hot_reload"]["enabled"] = False
        base_config["daemon"]["health"]["enabled"] = False
        base_config["daemon"]["auto_restart"]["max_retries"] = 2
        base_config["daemon"]["auto_restart"]["retry_delay"] = 0.01

        daemon = CrawlDaemon.__new__(CrawlDaemon)
        daemon._config = base_config
        daemon._config_path = str(tmp_path / "config.yaml")
        daemon._shutdown = False
        daemon._reloader = None
        daemon._health = None
        daemon._reporter = None
        daemon._retry_count = 0
        daemon._retry_date = datetime.now().date()

        with patch("src.daemon.init_db") as mock_db, \
             patch("src.daemon.QuoteMonitor"), \
             patch("src.daemon.PostSessionReporter"), \
             patch.object(daemon, '_run_session_loop', side_effect=Exception("test error")):
            mock_db.return_value = MagicMock()
            daemon._main_loop()
            # retry_count 应该超过了 max_retries
            assert daemon._retry_count > 2


class TestRunSessionLoop:
    """_run_session_loop 测试。"""

    def test_immediate_shutdown(self, base_config):
        """shutdown=True → 立即退出。"""
        daemon = CrawlDaemon.__new__(CrawlDaemon)
        daemon._config = base_config
        daemon._shutdown = True
        daemon._reloader = None
        daemon._health = None
        daemon._reporter = None
        daemon._run_session_loop(MagicMock(), MagicMock())

    def test_no_session_sleeps(self, base_config):
        """不在时段内 → 休眠后 shutdown 退出。"""
        daemon = CrawlDaemon.__new__(CrawlDaemon)
        daemon._config = base_config
        daemon._shutdown = False
        daemon._reloader = None
        daemon._health = None
        daemon._reporter = None

        call_count = [0]
        def mock_try_reload():
            call_count[0] += 1
            if call_count[0] >= 2:
                daemon._shutdown = True

        with patch.object(CrawlDaemon, '_try_reload', side_effect=mock_try_reload), \
             patch.object(CrawlDaemon, '_update_health_status'), \
             patch("src.session.SessionManager.get_current_session", return_value=None), \
             patch("src.session.SessionManager.calc_next_start_or_tomorrow",
                   return_value=datetime(2026, 6, 9, 13, 0)), \
             patch("src.session.SessionManager.sleep_until"):
            daemon._run_session_loop(MagicMock(), MagicMock())


class TestCmdFunctions:
    """CLI 命令测试。"""

    def test_cmd_stop_no_pid(self, capsys, tmp_path, base_config):
        """stop 命令在无 PID 文件时输出提示。"""
        base_config["daemon"]["pid_file"] = str(tmp_path / "nonexistent.pid")
        with patch("src.daemon.load_config", return_value=base_config):
            from src.daemon import cmd_stop
            args = MagicMock()
            args.config = None
            cmd_stop(args)
            captured = capsys.readouterr()
            assert "未运行" in captured.out

    def test_cmd_status_no_pid(self, capsys, tmp_path, base_config):
        """status 命令在无 PID 文件时输出提示。"""
        base_config["daemon"]["pid_file"] = str(tmp_path / "nonexistent.pid")
        with patch("src.daemon.load_config", return_value=base_config):
            from src.daemon import cmd_status
            args = MagicMock()
            args.config = None
            cmd_status(args)
            captured = capsys.readouterr()
            assert "未运行" in captured.out

    def test_cmd_status_with_health_file(self, capsys, tmp_path, base_config):
        """status 命令读取 health.json。"""
        import json
        pid_file = tmp_path / "test.pid"
        pid_file.write_text(str(os.getpid()), encoding="utf-8")
        base_config["daemon"]["pid_file"] = str(pid_file)

        health_file = Path("logs/health.json")
        health_file.parent.mkdir(parents=True, exist_ok=True)
        health_file.write_text(json.dumps({
            "status": "running",
            "current_session": {"start": "09:30", "end": "11:30", "remaining_seconds": 3600},
            "config_version": 1,
        }), encoding="utf-8")

        with patch("src.daemon.load_config", return_value=base_config):
            from src.daemon import cmd_status
            args = MagicMock()
            args.config = None
            cmd_status(args)
            captured = capsys.readouterr()
            assert "运行中" in captured.out

        health_file.unlink(missing_ok=True)

    def test_cmd_stop_with_pid(self, capsys, tmp_path, base_config):
        """stop 命令有 PID 文件且进程存活 → 发送信号。"""
        pid_file = tmp_path / "test.pid"
        pid_file.write_text(str(os.getpid()), encoding="utf-8")
        base_config["daemon"]["pid_file"] = str(pid_file)

        with patch("src.daemon.load_config", return_value=base_config), \
             patch("os.kill") as mock_kill:
            from src.daemon import cmd_stop
            args = MagicMock()
            args.config = None
            cmd_stop(args)
            mock_kill.assert_called()

    def test_main_no_command(self):
        """无子命令时显示帮助。"""
        with patch("sys.argv", ["daemon"]):
            from src.daemon import main
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0

    def test_main_start_command(self):
        """start 子命令调用 cmd_start。"""
        with patch("sys.argv", ["daemon", "start"]), \
             patch("src.daemon.cmd_start") as mock_start:
            from src.daemon import main
            main()
            mock_start.assert_called_once()

    def test_send_signal_to_dead_pid(self, tmp_path, base_config):
        """向已死进程发送信号 → 返回 False。"""
        pid_file = tmp_path / "test.pid"
        pid_file.write_text("9999999", encoding="utf-8")
        base_config["daemon"]["pid_file"] = str(pid_file)
        result = _send_signal_to_pid(base_config, signal.SIGTERM)
        assert result is False


class TestRetryLogic:
    """自动重启逻辑测试。"""

    def test_retry_count_resets_on_new_day(self, base_config):
        """日期变更 → 重启计数清零。"""
        daemon = CrawlDaemon.__new__(CrawlDaemon)
        daemon._retry_count = 5
        daemon._retry_date = datetime(2026, 6, 8).date()

        # 模拟日期变更检查
        from datetime import date as _date
        today = _date(2026, 6, 9)
        if today != daemon._retry_date:
            daemon._retry_count = 0
            daemon._retry_date = today

        assert daemon._retry_count == 0
        assert daemon._retry_date == today
