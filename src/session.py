"""时间窗口引擎 — 判断当前交易时段、计算下一窗口。"""

import logging
import time as _time_mod
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Callable

logger = logging.getLogger(__name__)


@dataclass
class SessionWindow:
    """一个交易时间窗口。"""
    start: time
    end: time
    symbols: list[str] = field(default_factory=list)

    @property
    def is_overnight(self) -> bool:
        """窗口是否跨越午夜（如 23:00-01:00）。"""
        return self.end < self.start

    @property
    def start_str(self) -> str:
        return self.start.strftime("%H:%M")

    @property
    def end_str(self) -> str:
        return self.end.strftime("%H:%M")

    def contains(self, t: time) -> bool:
        """判断时间 t 是否在窗口内。start <= t < end。"""
        if self.is_overnight:
            return t >= self.start or t < self.end
        return self.start <= t < self.end


class SessionManager:
    """管理交易时间窗口，根据配置决定何时采集。"""

    def __init__(self, config: dict) -> None:
        self._all_symbols: list[str] = list(config.get("symbols", []))
        self._windows: list[SessionWindow] = self._parse_sessions(config)

    def _parse_sessions(self, config: dict) -> list[SessionWindow]:
        """从配置解析所有时间窗口。返回按 start 排序的窗口列表。"""
        sessions = config.get("sessions", {})
        default_defs = sessions.get("default", [])
        overrides = sessions.get("overrides", {})

        windows: list[SessionWindow] = []

        # 默认窗口：应用于所有未 override 的 symbol
        overridden_symbols = set(overrides.keys())
        default_symbols = [s for s in self._all_symbols if s not in overridden_symbols]

        if default_defs:
            for w in default_defs:
                windows.append(SessionWindow(
                    start=_parse_time(w["start"]),
                    end=_parse_time(w["end"]),
                    symbols=list(default_symbols),
                ))

        # Override 窗口：每个 symbol 独立的时段
        for sym, sym_windows in overrides.items():
            if sym not in self._all_symbols:
                continue
            for w in sym_windows:
                windows.append(SessionWindow(
                    start=_parse_time(w["start"]),
                    end=_parse_time(w["end"]),
                    symbols=[sym],
                ))

        # 按 start 排序
        windows.sort(key=lambda w: w.start)
        return windows

    def get_current_session(self, now: datetime | None = None) -> SessionWindow | None:
        """返回当前应采集的窗口，不在任何窗口内返回 None。

        如果多个窗口重叠，返回第一个匹配的（按 start 排序）。
        """
        if now is None:
            now = datetime.now()
        t = now.time()
        for w in self._windows:
            if w.contains(t):
                return w
        return None

    def get_active_symbols(self) -> list[str]:
        """返回所有参与采集的 symbols（去重，保持顺序）。"""
        seen: set[str] = set()
        result: list[str] = []
        for w in self._windows:
            for s in w.symbols:
                if s not in seen:
                    seen.add(s)
                    result.append(s)
        return result

    def calc_next_start(self, now: datetime | None = None) -> datetime | None:
        """计算下一个窗口的开始时间。今日无更多窗口返回 None。"""
        if now is None:
            now = datetime.now()
        t = now.time()

        for w in self._windows:
            if w.start > t:
                return now.replace(
                    hour=w.start.hour, minute=w.start.minute,
                    second=0, microsecond=0,
                )

        # 检查跨日窗口：如果 start < end 不成立（跨日），且当前时间 < end
        # 则该窗口实际上从昨天开始，今天已过
        return None

    def calc_next_start_or_tomorrow(self, now: datetime | None = None) -> datetime:
        """计算下一个窗口开始时间，今日无则返回明日第一个窗口。"""
        result = self.calc_next_start(now)
        if result is not None:
            return result

        if now is None:
            now = datetime.now()
        if self._windows:
            first = self._windows[0]
            tomorrow = now + timedelta(days=1)
            return tomorrow.replace(
                hour=first.start.hour, minute=first.start.minute,
                second=0, microsecond=0,
            )

        # 无任何窗口配置，返回 1 小时后（避免空转）
        return now + timedelta(hours=1)

    @staticmethod
    def sleep_until(
        target: datetime,
        interrupt_check: Callable[[], bool],
        interval: float = 1.0,
    ) -> None:
        """可中断的休眠。每 interval 秒检查 interrupt_check()。"""
        while True:
            if interrupt_check():
                logger.debug("sleep_until interrupted")
                return
            remaining = (target - datetime.now()).total_seconds()
            if remaining <= 0:
                return
            _time_mod.sleep(min(interval, remaining))


def _parse_time(s: str) -> time:
    """将 'HH:MM' 字符串转为 time 对象。"""
    parts = s.split(":")
    return time(int(parts[0]), int(parts[1]))
