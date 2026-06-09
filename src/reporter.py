"""盘后自动报告 — 交易窗口结束后生成报告并可选清理。"""

import logging
from datetime import date
from pathlib import Path

import sqlite3

logger = logging.getLogger(__name__)


class PostSessionReporter:
    """每个交易窗口结束后自动生成分析报告。"""

    def __init__(self, config: dict, conn: sqlite3.Connection) -> None:
        self._config = config
        self._conn = conn
        cfg = config.get("daemon", {}).get("post_market_report", {})
        self._enabled: bool = cfg.get("enabled", True)
        self._output_dir: str = cfg.get("output_dir", "reports/")
        self._auto_cleanup: bool = cfg.get("auto_cleanup", True)

    def generate(
        self,
        symbols: list[str],
        session_start: str,
        session_end: str,
    ) -> str | None:
        """生成盘后报告。返回报告文件路径，失败返回 None。"""
        if not self._enabled:
            return None

        try:
            return self._do_generate(symbols, session_start, session_end)
        except Exception as e:
            logger.error("盘后报告生成失败: %s", e)
            return None

    def _do_generate(
        self,
        symbols: list[str],
        session_start: str,
        session_end: str,
    ) -> str:
        from src.analyze import generate_report

        today = date.today().isoformat()
        report = generate_report(self._conn, self._config, today, symbols)

        # 写入文件
        output_dir = Path(self._output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        start_tag = session_start.replace(":", "")
        end_tag = session_end.replace(":", "")
        filename = f"{today}_session_{start_tag}_{end_tag}.md"
        filepath = output_dir / filename

        filepath.write_text(report, encoding="utf-8")
        logger.info("盘后报告已生成: %s", filepath)

        # 可选清理
        if self._auto_cleanup:
            try:
                from src.maintenance import run_retention_cleanup
                run_retention_cleanup(self._conn, self._config)
                logger.info("盘后数据清理完成")
            except Exception as e:
                logger.warning("盘后清理失败: %s", e)

        return str(filepath)
