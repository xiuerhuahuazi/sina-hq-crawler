import pytest
import sqlite3
import sys
import platform
import os
from pathlib import Path

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import _DEFAULTS, _deep_merge
from src.db import init_db


def get_environment_info():
    """获取当前环境信息。"""
    info = {
        "os": platform.system(),
        "architecture": platform.machine(),
        "is_wsl": False,
        "is_macos": platform.system() == "Darwin",
        "is_linux": platform.system() == "Linux",
        "is_arm64": platform.machine() == "arm64",
    }

    # 检测WSL
    if info["is_linux"]:
        try:
            with open('/proc/version', 'r') as f:
                version_info = f.read().lower()
                info["is_wsl"] = "microsoft" in version_info
        except:
            pass

    return info


@pytest.fixture(autouse=True)
def environment_setup(request):
    """环境配置fixture。"""
    env_info = get_environment_info()

    # 根据环境设置超时（通过配置文件，不使用mark）
    # pytest-timeout 插件会自动应用 pytest.ini 中的 timeout 设置

    # 存储环境信息供测试使用
    request.node._env_info = env_info


@pytest.fixture(autouse=True)
def cleanup_resources():
    """自动清理测试资源，防止线程泄漏。"""
    yield
    # 测试结束后强制垃圾回收
    import gc
    gc.collect()


@pytest.fixture
def env_info(environment_setup):
    """提供环境信息给测试。"""
    return environment_setup._env_info


@pytest.fixture
def base_config():
    """Minimal valid config dict with all required nested keys."""
    return _deep_merge(_DEFAULTS, {
        "symbols": ["sh000001", "bj920576"],
        "crawl": {
            "poll_interval": 3,
            "test_duration": 1,
            "batch_commit_size": 5,
            "batch_commit_interval": 60,
        },
        "http": {
            "api_url": "https://hq.sinajs.cn/rn={ts}&list={symbols}",
            "timeout": 10,
            "max_retries": 2,
            "retry_base_delay": 0.01,
            "retry_max_delay": 0.1,
            "headers": {
                "Referer": "https://finance.sina.com.cn/",
                "User-Agent": "TestAgent",
            },
        },
        "concurrency": {
            "enabled": "false",
            "max_workers": 2,
            "auto_threshold": 6,
            "batch_size": 4,
        },
        "logging": {
            "level": "WARNING",
            "file": "logs/test.log",
            "max_bytes": 1024,
            "backup_count": 1,
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        },
        "monitor": {
            "enabled": True,
            "latency_warn_ms": 500,
            "latency_critical_ms": 2000,
            "gap_threshold_seconds": 15,
            "price_spike_pct": 3.0,
            "alert_to": "console",
            "alert_file": "logs/test_alerts.log",
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
            "health": {"enabled": False, "host": "127.0.0.1", "port": 8089},
            "hot_reload": {"enabled": False, "watch_file": "config.yaml"},
            "post_market_report": {"enabled": False, "output_dir": "reports/", "auto_cleanup": False},
            "auto_restart": {"enabled": True, "max_retries": 3, "retry_delay": 1},
        },
    })


@pytest.fixture
def db_conn(base_config, tmp_path):
    """In-memory SQLite connection with all tables/views created."""
    db_path = str(tmp_path / "test.db")
    conn = init_db(db_path, base_config)
    yield conn
    conn.close()


@pytest.fixture
def db_conn_memory(base_config):
    """Pure in-memory SQLite connection (no file)."""
    conn = init_db(":memory:", base_config)
    yield conn
    conn.close()


SH_INDEX_LINE = (
    'var hq_str_sh000001="上证指数,4044.8292,4057.7811,4042.6525,4078.9317,'
    '4038.0447,0,0,559541192,1151469946916,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,'
    '2026-06-05,14:19:41,00,"'
)

BJ_STOCK_LINE = (
    'var hq_str_bj920576="天力复合,58.390,56.840,69.690,70.510,57.700,'
    '69.600,300,69.470,7765,69.460,59,69.430,1100,69.420,99,'
    '69.690,158,69.700,5186,69.720,1700,69.740,16557,69.750,1042,'
    '69.750,2026-06-05,14:29:51,00,304.9356,0.0000,0,8300000,B,T"'
)


@pytest.fixture
def sh_index_line():
    return SH_INDEX_LINE


@pytest.fixture
def bj_stock_line():
    return BJ_STOCK_LINE


@pytest.fixture
def sample_quotes(sh_index_line, bj_stock_line):
    """Parsed quotes from test data."""
    from src.parser import parse_response
    return parse_response(sh_index_line + "\n" + bj_stock_line)
