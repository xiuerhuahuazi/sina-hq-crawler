"""Monitoring and alerting engine for real-time quote feeds."""

import logging
import time
from datetime import datetime
from pathlib import Path


class QuoteMonitor:
    """Track tick latency, price spikes, and data gaps; emit alerts."""

    def __init__(self, config: dict) -> None:
        mon = config["monitor"]

        self._enabled: bool = mon.get("enabled", True)

        # Thresholds
        self._latency_warn_ms: float = mon.get("latency_warn_ms", 500)
        self._latency_critical_ms: float = mon.get("latency_critical_ms", 2000)
        self._gap_threshold_seconds: float = mon.get("gap_threshold_seconds", 30)
        self._price_spike_pct: float = mon.get("price_spike_pct", 5.0)

        self._alert_to: str = mon.get("alert_to", "console")  # 'console' / 'file' / 'both'

        # Per-symbol monotonic timestamp of the last received tick.
        self._last_tick_time: dict[str, float] = {}

        # Consecutive fetch-error counter.
        self._consecutive_failures: int = 0

        # Stats
        self._total_ticks: int = 0
        self._total_alerts: int = 0
        self._alert_counts: dict[str, int] = {}

        # Dedicated alert logger (writes to its own file when configured).
        self._alert_logger = logging.getLogger("monitor.alerts")
        self._alert_logger.propagate = False  # don't bubble to root handlers
        if self._alert_to in ("file", "both"):
            alert_path = Path(mon.get("alert_file", "logs/alerts.log"))
            alert_path.parent.mkdir(parents=True, exist_ok=True)
            fh = logging.FileHandler(str(alert_path), encoding="utf-8")
            fh.setFormatter(logging.Formatter("%(message)s"))
            self._alert_logger.addHandler(fh)
        self._alert_logger.setLevel(logging.DEBUG)

        # Standard logger for informational messages.
        self._logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def on_tick(
        self,
        symbol: str,
        current: float,
        prev_close: float,
        latency_ms: float,
    ) -> None:
        """Process an incoming tick; check latency and price spike."""
        if not self._enabled:
            return

        self._total_ticks += 1

        # --- latency checks ---
        if latency_ms >= self._latency_critical_ms:
            self._alert(
                "CRITICAL",
                f"[{symbol}] Latency {latency_ms:.0f}ms exceeds critical threshold "
                f"({self._latency_critical_ms:.0f}ms)",
            )
        elif latency_ms >= self._latency_warn_ms:
            self._alert(
                "WARNING",
                f"[{symbol}] Latency {latency_ms:.0f}ms exceeds warning threshold "
                f"({self._latency_warn_ms:.0f}ms)",
            )

        # --- price spike check ---
        if prev_close and current:
            change_pct = abs(current / prev_close - 1) * 100
            if change_pct > self._price_spike_pct:
                self._alert(
                    "WARNING",
                    f"[{symbol}] Price spike {change_pct:.2f}% "
                    f"(current={current}, prev_close={prev_close})",
                )

        # --- bookkeeping ---
        self._last_tick_time[symbol] = time.monotonic()
        self._consecutive_failures = 0

    def on_fetch_error(self, error: Exception) -> None:
        """Record a fetch failure; alert after 3 consecutive errors."""
        self._consecutive_failures += 1
        if self._consecutive_failures >= 3:
            self._alert(
                "CRITICAL",
                f"Fetch failed {self._consecutive_failures} consecutive times: {error}",
            )

    def check_gaps(self, symbols: list[str]) -> None:
        """Alert if any symbol has gone silent beyond the gap threshold."""
        if not self._enabled:
            return

        now = time.monotonic()
        for sym in symbols:
            last = self._last_tick_time.get(sym)
            if last is not None and (now - last) > self._gap_threshold_seconds:
                self._alert(
                    "CRITICAL",
                    f"[{sym}] Data gap detected: "
                    f"{now - last:.1f}s since last tick "
                    f"(threshold {self._gap_threshold_seconds:.0f}s)",
                )

    def get_stats(self) -> dict:
        """Return a snapshot of current monitoring statistics."""
        return {
            "total_ticks": self._total_ticks,
            "total_alerts": self._total_alerts,
            "alert_counts": dict(self._alert_counts),
            "consecutive_failures": self._consecutive_failures,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _alert(self, level: str, message: str) -> None:
        """Emit an alert through the configured channels."""
        self._total_alerts += 1
        self._alert_counts[level] = self._alert_counts.get(level, 0) + 1

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        formatted = f"[{ts}] [{level}] {message}"

        # Always write to the dedicated alert logger (file handler if configured).
        self._alert_logger.warning(formatted)

        # Console output with ANSI colour when requested.
        if self._alert_to in ("console", "both"):
            yellow = "\033[93m"
            reset = "\033[0m"
            print(f"{yellow}{formatted}{reset}")

        # Also log through the standard module logger at the matching level.
        numeric = logging.getLevelName(level)
        if isinstance(numeric, int):
            self._logger.log(numeric, message)
        else:
            self._logger.warning(message)
