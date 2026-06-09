"""Tests for src/session.py — 时间窗口引擎。"""

import pytest
from datetime import datetime, time

from src.session import SessionManager, SessionWindow, _parse_time


class TestSessionWindow:
    """SessionWindow 数据类测试。"""

    def test_contains_normal_window(self):
        """正常窗口 09:30-11:30，10:00 在窗口内。"""
        w = SessionWindow(start=time(9, 30), end=time(11, 30))
        assert w.contains(time(10, 0)) is True

    def test_contains_at_start(self):
        """恰好等于 start → 在窗口内。"""
        w = SessionWindow(start=time(9, 30), end=time(11, 30))
        assert w.contains(time(9, 30)) is True

    def test_contains_at_end(self):
        """恰好等于 end → 不在窗口内（start <= t < end）。"""
        w = SessionWindow(start=time(9, 30), end=time(11, 30))
        assert w.contains(time(11, 30)) is False

    def test_contains_before_start(self):
        """start 之前不在窗口内。"""
        w = SessionWindow(start=time(9, 30), end=time(11, 30))
        assert w.contains(time(9, 0)) is False

    def test_contains_after_end(self):
        """end 之后不在窗口内。"""
        w = SessionWindow(start=time(9, 30), end=time(11, 30))
        assert w.contains(time(12, 0)) is False

    def test_overnight_window(self):
        """跨日窗口 23:00-01:00。"""
        w = SessionWindow(start=time(23, 0), end=time(1, 0))
        assert w.is_overnight is True
        assert w.contains(time(23, 30)) is True
        assert w.contains(time(0, 30)) is True
        assert w.contains(time(2, 0)) is False

    def test_overnight_at_boundary(self):
        """跨日窗口边界。"""
        w = SessionWindow(start=time(23, 0), end=time(1, 0))
        assert w.contains(time(23, 0)) is True  # start
        assert w.contains(time(1, 0)) is False   # end
        assert w.contains(time(12, 0)) is False   # 中午

    def test_str_properties(self):
        w = SessionWindow(start=time(9, 30), end=time(11, 30))
        assert w.start_str == "09:30"
        assert w.end_str == "11:30"


class TestParseTime:
    """_parse_time 辅助函数测试。"""

    def test_valid(self):
        assert _parse_time("09:30") == time(9, 30)
        assert _parse_time("00:00") == time(0, 0)
        assert _parse_time("23:59") == time(23, 59)

    def test_single_digit(self):
        assert _parse_time("9:30") == time(9, 30)


class TestSessionManager:
    """SessionManager 测试。"""

    @pytest.fixture
    def default_config(self):
        return {
            "symbols": ["sh000001", "bj920576"],
            "sessions": {
                "default": [
                    {"start": "09:30", "end": "11:30"},
                    {"start": "13:00", "end": "15:00"},
                ],
                "overrides": {},
            },
        }

    @pytest.fixture
    def override_config(self):
        return {
            "symbols": ["sh000001", "bj920576"],
            "sessions": {
                "default": [
                    {"start": "09:30", "end": "11:30"},
                    {"start": "13:00", "end": "15:00"},
                ],
                "overrides": {
                    "sh000001": [
                        {"start": "09:15", "end": "15:15"},
                    ],
                },
            },
        }

    def test_default_windows_parsed(self, default_config):
        """默认配置解析出两个窗口。"""
        mgr = SessionManager(default_config)
        assert len(mgr._windows) == 2

    def test_in_morning_session(self, default_config):
        """09:30-11:30 窗口内，两个 symbol 都在。"""
        mgr = SessionManager(default_config)
        now = datetime(2026, 6, 9, 10, 0)
        session = mgr.get_current_session(now)
        assert session is not None
        assert session.start == time(9, 30)
        assert session.end == time(11, 30)
        assert set(session.symbols) == {"sh000001", "bj920576"}

    def test_in_afternoon_session(self, default_config):
        """13:00-15:00 窗口内。"""
        mgr = SessionManager(default_config)
        now = datetime(2026, 6, 9, 14, 0)
        session = mgr.get_current_session(now)
        assert session is not None
        assert session.start == time(13, 0)

    def test_outside_sessions(self, default_config):
        """午休时间 12:00 不在任何窗口。"""
        mgr = SessionManager(default_config)
        now = datetime(2026, 6, 9, 12, 0)
        assert mgr.get_current_session(now) is None

    def test_before_market(self, default_config):
        """08:00 不在任何窗口。"""
        mgr = SessionManager(default_config)
        now = datetime(2026, 6, 9, 8, 0)
        assert mgr.get_current_session(now) is None

    def test_after_market(self, default_config):
        """16:00 不在任何窗口。"""
        mgr = SessionManager(default_config)
        now = datetime(2026, 6, 9, 16, 0)
        assert mgr.get_current_session(now) is None

    def test_override_creates_separate_window(self, override_config):
        """override symbol 独立窗口，default 只含未 override 的 symbol。"""
        mgr = SessionManager(override_config)
        now = datetime(2026, 6, 9, 10, 0)
        session = mgr.get_current_session(now)
        # sh000001 有 override，所以 default 窗口只有 bj920576
        # sh000001 的 override 窗口 09:15-15:15 也包含 10:00
        # 但默认窗口按 start 排序，09:15 排在 09:30 前面
        assert session is not None
        # sh000001 的 override 窗口 start=09:15 排在前面
        assert "sh000001" in session.symbols

    def test_override_default_symbols(self, override_config):
        """override 后 default 窗口只含未 override 的 symbol。"""
        mgr = SessionManager(override_config)
        # 13:00 下午窗口：sh000001 有 override 09:15-15:15
        # 此时 get_current_session 会先匹配 sh000001 的 override 窗口（start=09:15）
        now = datetime(2026, 6, 9, 13, 0)
        session = mgr.get_current_session(now)
        assert session is not None
        # sh000001 的 override 09:15-15:15 包含 13:00，排在前面
        assert session.symbols == ["sh000001"]

    def test_active_symbols(self, override_config):
        """get_active_symbols 返回所有 symbol。"""
        mgr = SessionManager(override_config)
        symbols = mgr.get_active_symbols()
        assert set(symbols) == {"sh000001", "bj920576"}

    def test_calc_next_start(self, default_config):
        """10:00 时下一窗口 start 是 13:00。"""
        mgr = SessionManager(default_config)
        now = datetime(2026, 6, 9, 10, 0)
        result = mgr.calc_next_start(now)
        assert result is not None
        assert result.hour == 13
        assert result.minute == 0

    def test_calc_next_start_afternoon(self, default_config):
        """14:00 时今日无更多窗口。"""
        mgr = SessionManager(default_config)
        now = datetime(2026, 6, 9, 14, 0)
        assert mgr.calc_next_start(now) is None

    def test_calc_next_start_morning_before(self, default_config):
        """08:00 时下一窗口是 09:30。"""
        mgr = SessionManager(default_config)
        now = datetime(2026, 6, 9, 8, 0)
        result = mgr.calc_next_start(now)
        assert result is not None
        assert result.hour == 9
        assert result.minute == 30

    def test_calc_next_start_or_tomorrow(self, default_config):
        """今日无更多窗口时返回明日第一个窗口。"""
        mgr = SessionManager(default_config)
        now = datetime(2026, 6, 9, 16, 0)
        result = mgr.calc_next_start_or_tomorrow(now)
        assert result.day == 10
        assert result.hour == 9
        assert result.minute == 30

    def test_empty_sessions(self):
        """空 sessions 配置始终返回 None。"""
        config = {
            "symbols": ["sh000001"],
            "sessions": {"default": [], "overrides": {}},
        }
        mgr = SessionManager(config)
        assert mgr.get_current_session() is None

    def test_empty_symbols(self):
        """空 symbols 列表。"""
        config = {
            "symbols": [],
            "sessions": {
                "default": [{"start": "09:30", "end": "11:30"}],
                "overrides": {},
            },
        }
        mgr = SessionManager(config)
        assert mgr.get_active_symbols() == []
        # 无 symbol 的窗口仍会存在
        now = datetime(2026, 6, 9, 10, 0)
        session = mgr.get_current_session(now)
        assert session is not None
        assert session.symbols == []

    def test_sleep_until_interrupts(self):
        """sleep_until 在 interrupt_check 返回 True 时提前退出。"""
        import time as _time
        calls = [0]
        def check():
            calls[0] += 1
            return calls[0] >= 3

        from datetime import timedelta
        target = datetime.now() + timedelta(hours=1)
        SessionManager.sleep_until(target, check, interval=0.01)
        assert calls[0] >= 3

    def test_sleep_until_reaches_target(self):
        """sleep_until 在 target 到达时退出。"""
        from datetime import timedelta
        target = datetime.now() + timedelta(milliseconds=50)
        SessionManager.sleep_until(target, lambda: False, interval=0.01)
        # 不会无限阻塞

    def test_override_ignores_unknown_symbol(self):
        """override 中不存在于 symbols 的 symbol 被忽略。"""
        config = {
            "symbols": ["sh000001"],
            "sessions": {
                "default": [{"start": "09:30", "end": "11:30"}],
                "overrides": {
                    "sz000001": [{"start": "10:00", "end": "12:00"}],
                },
            },
        }
        mgr = SessionManager(config)
        assert len(mgr._windows) == 1  # 只有 default 窗口
        assert mgr._windows[0].symbols == ["sh000001"]
