"""Tests for src/reporter.py — 盘后自动报告。"""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import date

from src.reporter import PostSessionReporter


class TestPostSessionReporter:
    """PostSessionReporter 测试。"""

    def test_disabled_returns_none(self, base_config, db_conn):
        """reporter 禁用时返回 None。"""
        base_config["daemon"]["post_market_report"]["enabled"] = False
        reporter = PostSessionReporter(base_config, db_conn)
        result = reporter.generate(["sh000001"], "09:30", "11:30")
        assert result is None

    @patch("src.analyze.generate_report")
    def test_generate_creates_file(self, mock_report, base_config, db_conn, tmp_path):
        """正常生成 → 文件存在。"""
        mock_report.return_value = "# 测试报告\n数据正常\n"
        base_config["daemon"]["post_market_report"]["enabled"] = True
        base_config["daemon"]["post_market_report"]["output_dir"] = str(tmp_path / "reports")
        base_config["daemon"]["post_market_report"]["auto_cleanup"] = False

        reporter = PostSessionReporter(base_config, db_conn)
        result = reporter.generate(["sh000001"], "09:30", "11:30")

        assert result is not None
        filepath = Path(result)
        assert filepath.exists()
        assert filepath.read_text(encoding="utf-8") == "# 测试报告\n数据正常\n"

    @patch("src.analyze.generate_report")
    def test_generate_filename_format(self, mock_report, base_config, db_conn, tmp_path):
        """文件名格式: YYYY-MM-DD_session_HHMM_HHMM.md。"""
        mock_report.return_value = "content"
        base_config["daemon"]["post_market_report"]["enabled"] = True
        base_config["daemon"]["post_market_report"]["output_dir"] = str(tmp_path)
        base_config["daemon"]["post_market_report"]["auto_cleanup"] = False

        reporter = PostSessionReporter(base_config, db_conn)
        result = reporter.generate(["sh000001"], "09:30", "11:30")

        assert result is not None
        today = date.today().isoformat()
        assert f"{today}_session_0930_1130.md" in result

    @patch("src.maintenance.run_retention_cleanup")
    @patch("src.analyze.generate_report")
    def test_auto_cleanup_calls_maintenance(
        self, mock_report, mock_cleanup, base_config, db_conn, tmp_path
    ):
        """auto_cleanup=True → maintenance 被调用。"""
        mock_report.return_value = "content"
        base_config["daemon"]["post_market_report"]["enabled"] = True
        base_config["daemon"]["post_market_report"]["output_dir"] = str(tmp_path)
        base_config["daemon"]["post_market_report"]["auto_cleanup"] = True

        reporter = PostSessionReporter(base_config, db_conn)
        reporter.generate(["sh000001"], "09:30", "11:30")

        mock_cleanup.assert_called_once_with(db_conn, base_config)

    @patch("src.analyze.generate_report")
    def test_auto_cleanup_false(self, mock_report, base_config, db_conn, tmp_path):
        """auto_cleanup=False → maintenance 不被调用。"""
        mock_report.return_value = "content"
        base_config["daemon"]["post_market_report"]["enabled"] = True
        base_config["daemon"]["post_market_report"]["output_dir"] = str(tmp_path)
        base_config["daemon"]["post_market_report"]["auto_cleanup"] = False

        with patch("src.maintenance.run_retention_cleanup") as mock_cleanup:
            reporter = PostSessionReporter(base_config, db_conn)
            reporter.generate(["sh000001"], "09:30", "11:30")
            mock_cleanup.assert_not_called()

    @patch("src.analyze.generate_report", side_effect=Exception("db error"))
    def test_generate_failure_returns_none(self, mock_report, base_config, db_conn):
        """生成失败 → 返回 None，不抛异常。"""
        base_config["daemon"]["post_market_report"]["enabled"] = True
        reporter = PostSessionReporter(base_config, db_conn)
        result = reporter.generate(["sh000001"], "09:30", "11:30")
        assert result is None
