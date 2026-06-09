"""Config loader — reads YAML config and merges with hardcoded defaults."""

import logging
import pathlib
import re
import yaml

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Hard-coded defaults — every key the rest of the codebase may read.
# Nested dicts represent dotted keys (e.g. concurrency.max_workers).
# ---------------------------------------------------------------------------

_DEFAULTS: dict = {
    "symbols": [],
    "crawl": {
        "poll_interval": 3,
        "test_duration": 0,
        "batch_commit_size": 20,
        "batch_commit_interval": 10,
    },
    "http": {
        "api_url": "https://hq.sinajs.cn/rn={ts}&list={symbols}",
        "timeout": 10,
        "max_retries": 3,
        "retry_base_delay": 1.0,
        "retry_max_delay": 30.0,
        "headers": {
            "Referer": "https://finance.sina.com.cn/",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
        },
    },
    "concurrency": {
        "enabled": "auto",
        "max_workers": 4,
        "auto_threshold": 6,
        "batch_size": 4,
    },
    "database": {
        "path": "hq_data.db",
        "wal_mode": True,
        "cache_size": -4000,
        "busy_timeout": 5000,
    },
    "logging": {
        "level": "INFO",
        "file": "logs/crawler.log",
        "max_bytes": 10485760,
        "backup_count": 5,
        "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    },
    "monitor": {
        "enabled": True,
        "latency_warn_ms": 500,
        "latency_critical_ms": 2000,
        "gap_threshold_seconds": 15,
        "price_spike_pct": 3.0,
        "alert_to": "console",
        "alert_file": "logs/alerts.log",
    },
    "retention": {
        "ods_days": 7,
        "dwd_days": 90,
        "dws_days": 365,
        "compress_on_cleanup": True,
        "archive_dir": "archives/",
    },
    "sessions": {
        "default": [
            {"start": "09:30", "end": "11:30"},
            {"start": "13:00", "end": "15:00"},
        ],
        "overrides": {},
    },
    "daemon": {
        "pid_file": "logs/crawler.pid",
        "health": {"enabled": True, "host": "127.0.0.1", "port": 8089},
        "hot_reload": {"enabled": True, "watch_file": "config.yaml"},
        "post_market_report": {"enabled": True, "output_dir": "reports/", "auto_cleanup": True},
        "auto_restart": {"enabled": True, "max_retries": 5, "retry_delay": 10},
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge *override* into a copy of *base*."""
    merged = base.copy()
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


_HH_MM_RE = re.compile(r"^\d{2}:\d{2}$")


def _validate_time_window(window: dict, path: str) -> None:
    """Validate a single time window has start/end in HH:MM format."""
    for field in ("start", "end"):
        val = window.get(field)
        if not val or not _HH_MM_RE.match(str(val)):
            raise ValueError(
                f"{path}.{field} must be in HH:MM format, got: {val!r}"
            )
        hh, mm = int(val[:2]), int(val[3:])
        if hh > 23 or mm > 59:
            raise ValueError(
                f"{path}.{field} has invalid time value: {val!r}"
            )


def _validate(cfg: dict) -> None:
    """Raise ``ValueError`` if mandatory constraints are violated."""
    symbols = cfg.get("symbols", [])
    if not isinstance(symbols, list) or len(symbols) == 0:
        raise ValueError(
            "config 'symbols' must be a non-empty list of stock symbol strings"
        )

    poll_interval = cfg.get("crawl", {}).get("poll_interval", 0)
    if poll_interval <= 0:
        raise ValueError(
            f"config 'crawl.poll_interval' must be > 0, got {poll_interval}"
        )

    api_url = cfg.get("http", {}).get("api_url", "")
    if "{ts}" not in api_url or "{symbols}" not in api_url:
        raise ValueError(
            "config 'http.api_url' must contain both {ts} and {symbols} placeholders, "
            f"got: {api_url!r}"
        )

    # Validate sessions
    sessions = cfg.get("sessions", {})
    default_windows = sessions.get("default", [])
    if not isinstance(default_windows, list):
        raise ValueError("config 'sessions.default' must be a list")
    for i, w in enumerate(default_windows):
        _validate_time_window(w, f"sessions.default[{i}]")

    overrides = sessions.get("overrides", {})
    if not isinstance(overrides, dict):
        raise ValueError("config 'sessions.overrides' must be a dict")
    for sym, windows in overrides.items():
        if not isinstance(windows, list):
            raise ValueError(f"config 'sessions.overrides.{sym}' must be a list")
        for i, w in enumerate(windows):
            _validate_time_window(w, f"sessions.overrides.{sym}[{i}]")

    # Validate daemon.health.port
    port = cfg.get("daemon", {}).get("health", {}).get("port", 8089)
    if not (1024 <= port <= 65535):
        raise ValueError(
            f"config 'daemon.health.port' must be 1024-65535, got {port}"
        )

    # Validate daemon.auto_restart.max_retries
    max_retries = cfg.get("daemon", {}).get("auto_restart", {}).get("max_retries", 5)
    if max_retries < 0:
        raise ValueError(
            f"config 'daemon.auto_restart.max_retries' must be >= 0, got {max_retries}"
        )


def load_config(path: str | None = None) -> dict:
    """Load configuration from *path* (YAML) and merge with defaults.

    Parameters
    ----------
    path:
        Explicit path to a YAML config file.  When *None* the loader looks
        for ``config.yaml`` in the project root (parent of ``src/``).

    Returns
    -------
    dict
        Fully-populated configuration dictionary.

    Raises
    ------
    ValueError
        If the merged configuration fails validation.
    FileNotFoundError
        If *path* is explicit and does not exist.
    """
    if path is None:
        # Resolve project root: parent of the directory containing this file.
        project_root = pathlib.Path(__file__).resolve().parent.parent
        path = project_root / "config.yaml"
    else:
        path = pathlib.Path(path).resolve()

    if not path.exists():
        if path == pathlib.Path(__file__).resolve().parent.parent / "config.yaml":
            # Default path missing — use pure defaults.
            log.info("No config.yaml found at %s; using defaults", path)
            cfg = _DEFAULTS.copy()
            _validate(cfg)
            return cfg
        raise FileNotFoundError(f"Config file not found: {path}")

    log.debug("Loading config from %s", path)
    with open(path, "r", encoding="utf-8") as fh:
        user_cfg = yaml.safe_load(fh) or {}

    cfg = _deep_merge(_DEFAULTS, user_cfg)
    _validate(cfg)
    return cfg
