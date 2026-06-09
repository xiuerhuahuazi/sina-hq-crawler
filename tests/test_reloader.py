"""Tests for src/reloader.py — 配置热加载器。"""

import pytest
from pathlib import Path
from unittest.mock import patch
import time

from src.config import _DEFAULTS, _deep_merge
from src.reloader import ConfigReloader


class TestConfigReloader:
    """ConfigReloader 测试。"""

    def test_no_change_returns_none(self, tmp_path):
        """文件未变化 → 返回 None。"""
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text("symbols:\n  - sh000001\n", encoding="utf-8")

        reloader = ConfigReloader(cfg_path)
        result = reloader.check_reload()
        assert result is None

    def test_file_changed_returns_config(self, tmp_path):
        """文件变化 → 返回新配置。"""
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text("symbols:\n  - sh000001\n", encoding="utf-8")

        reloader = ConfigReloader(cfg_path)
        assert reloader.config_version == 1

        # 修改文件
        time.sleep(0.05)
        cfg_path.write_text("symbols:\n  - sz000001\n", encoding="utf-8")

        result = reloader.check_reload()
        assert result is not None
        assert "sz000001" in result["symbols"]
        assert reloader.config_version == 2

    def test_invalid_config_returns_none(self, tmp_path):
        """文件变化但内容无效 → 返回 None。"""
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text("symbols:\n  - sh000001\n", encoding="utf-8")

        reloader = ConfigReloader(cfg_path)

        time.sleep(0.05)
        # symbols 为空列表，违反校验
        cfg_path.write_text("symbols: []\n", encoding="utf-8")

        result = reloader.check_reload()
        assert result is None
        # version 不变
        assert reloader.config_version == 1

    def test_force_reload(self, tmp_path):
        """force_reload 无论 mtime 是否变化都重新加载。"""
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text("symbols:\n  - sh000001\n", encoding="utf-8")

        reloader = ConfigReloader(cfg_path)

        # mtime 未变，check_reload 返回 None
        assert reloader.check_reload() is None

        # force_reload 强制加载
        result = reloader.force_reload()
        assert result is not None
        assert reloader.config_version == 2

    def test_force_reload_invalid(self, tmp_path):
        """force_reload 失败 → 返回 None，version 不变。"""
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text("symbols:\n  - sh000001\n", encoding="utf-8")

        reloader = ConfigReloader(cfg_path)

        time.sleep(0.05)
        cfg_path.write_text("symbols: []\n", encoding="utf-8")

        result = reloader.force_reload()
        assert result is None
        assert reloader.config_version == 1

    def test_file_not_found(self, tmp_path):
        """文件不存在 → 初始 mtime 为 0，后续可检测到文件创建。"""
        cfg_path = tmp_path / "nonexistent.yaml"
        reloader = ConfigReloader(cfg_path)
        assert reloader.check_reload() is None

    def test_version_increments(self, tmp_path):
        """多次成功 reload → version 递增。"""
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text("symbols:\n  - sh000001\n", encoding="utf-8")

        reloader = ConfigReloader(cfg_path)
        assert reloader.config_version == 1

        for i in range(3):
            time.sleep(0.05)
            cfg_path.write_text(f"symbols:\n  - sh00000{i}\n", encoding="utf-8")
            result = reloader.force_reload()
            assert result is not None

        assert reloader.config_version == 4  # 1 + 3 reloads
