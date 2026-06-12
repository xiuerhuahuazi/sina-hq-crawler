"""Pipeline orchestrator — 顺序运行多智能体分析。"""

import argparse
import logging
import sqlite3
import sys
from datetime import date
from pathlib import Path

from src.agents.base import BaseAgent
from src.agents.market_analyst import MarketAnalyst
from src.agents.fundamentals_analyst import FundamentalsAnalyst
from src.agents.risk_analyst import RiskAnalyst
from src.agents.synthesizer import Synthesizer, format_analysis_report

logger = logging.getLogger(__name__)


class AnalysisPipeline:
    """顺序多智能体分析流水线。

    四个智能体依次执行：MarketAnalyst → FundamentalsAnalyst → RiskAnalyst → Synthesizer。
    通过共享 state dict 通信，无外部依赖。
    """

    def __init__(self, conn: sqlite3.Connection, config: dict) -> None:
        self._conn = conn
        self._config = config
        self._agents: list[BaseAgent] = [
            MarketAnalyst(conn, config),
            FundamentalsAnalyst(conn, config),
            RiskAnalyst(conn, config),
            Synthesizer(conn, config),
        ]

    def run(
        self,
        symbols: list[str] | None = None,
        analysis_date: str | None = None,
    ) -> dict:
        """执行完整流水线。返回最终 state dict。"""
        if symbols is None:
            symbols = self._config.get("symbols", [])
        if analysis_date is None:
            analysis_date = date.today().isoformat()

        state = {
            "conn": self._conn,
            "config": self._config,
            "symbols": symbols,
            "analysis_date": analysis_date,
            "market_assessment": None,
            "fundamentals_assessment": None,
            "risk_assessment": None,
            "final_assessment": None,
        }

        for agent in self._agents:
            logger.info("Running agent: %s", agent.name)
            try:
                agent.run(state)
            except Exception as e:
                logger.error("Agent %s failed: %s", agent.name, e)

        return state

    def format_report(self, state: dict) -> str:
        """渲染为 Markdown 报告。"""
        return format_analysis_report(state)


def main():
    """CLI 入口：uv run agents。"""
    parser = argparse.ArgumentParser(description="多智能体分析系统")
    parser.add_argument("--config", "-c", default=None, help="配置文件路径")
    parser.add_argument("--symbols", "-s", nargs="+", help="分析标的列表")
    parser.add_argument("--date", "-d", default=None, help="分析日期 (YYYY-MM-DD)")
    parser.add_argument("--output", "-o", default=None, help="报告输出路径")
    args = parser.parse_args()

    from src.config import load_config
    from src.logger import setup_logging
    from src.db import init_db

    config = load_config(args.config)
    setup_logging(config)

    symbols = args.symbols or config.get("symbols", [])
    if not symbols:
        logger.error("无分析标的，请在配置或命令行指定")
        sys.exit(1)

    conn = init_db(config["database"]["path"], config)
    pipeline = AnalysisPipeline(conn, config)

    logger.info("开始多智能体分析: %s", ", ".join(symbols))
    state = pipeline.run(symbols=symbols, analysis_date=args.date)
    report = pipeline.format_report(state)

    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
        logger.info("报告已写入: %s", args.output)
    else:
        print(report)

    conn.close()


if __name__ == "__main__":
    main()
