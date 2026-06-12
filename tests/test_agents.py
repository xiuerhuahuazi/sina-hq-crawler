"""Tests for src/agents/ — 多智能体分析系统。"""

import pytest
from datetime import datetime, date, timedelta
from src.db import init_db
from src.agents.base import BaseAgent
from src.agents.market_analyst import MarketAnalyst
from src.agents.fundamentals_analyst import FundamentalsAnalyst
from src.agents.risk_analyst import RiskAnalyst
from src.agents.synthesizer import Synthesizer, format_analysis_report
from src.agents.orchestrator import AnalysisPipeline
from src.agents.scorer import ProjectScorer


# ---- 测试数据辅助函数 ----

def _insert_daily(conn, symbol, trade_date, o, h, l, c, volume, amount, prev_close):
    conn.execute("""
        INSERT OR REPLACE INTO dws_daily_summary
        (symbol, trade_date, open, high, low, close, prev_close, volume, amount,
         change_pct, tick_count, first_tick_at, last_tick_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
    """, (symbol, trade_date, o, h, l, c, prev_close, volume, amount,
          round((c / prev_close - 1) * 100, 2) if prev_close else 0,
          f"{trade_date} 09:30:00", f"{trade_date} 15:00:00"))
    conn.commit()


def _insert_node_data(conn, symbol, name, per, pb, mktcap, nmc, turnover):
    conn.execute("""
        INSERT OR REPLACE INTO dwd_node_data
        (symbol, code, name, trade, pricechange, changepercent,
         buy, sell, settlement, open, high, low, volume, amount,
         ticktime, per, pb, mktcap, nmc, turnoverratio, fetched_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (symbol, symbol[-6:], name, 100.0, 1.0, 1.0,
          99.0, 101.0, 99.5, 99.0, 102.0, 98.0, 1e6, 1e8,
          "15:00:00", per, pb, mktcap, nmc, turnover,
          datetime.now().isoformat()))
    conn.commit()


def _populate_daily(conn, symbol, days=30):
    """插入 N 天日线数据。"""
    today = date.today()
    for i in range(days):
        d = (today - timedelta(days=days - i)).isoformat()
        base = 100 + i * 0.5
        _insert_daily(conn, symbol, d,
                      o=base, h=base + 2, l=base - 1, c=base + 1,
                      volume=1000000 + i * 10000,
                      amount=(base + 1) * (1000000 + i * 10000),
                      prev_close=base - 0.5)


# ---- Fixtures ----

@pytest.fixture
def conn(base_config, tmp_path):
    c = init_db(str(tmp_path / "test.db"), base_config)
    yield c
    c.close()


@pytest.fixture
def conn_with_data(conn):
    """包含日线 + 基本面数据的数据库。"""
    _populate_daily(conn, "sh000001", 30)
    _insert_node_data(conn, "sh000001", "上证指数", per=15.2, pb=1.8,
                      mktcap=5_200_000, nmc=4_800_000, turnover=0.5)
    return conn


@pytest.fixture
def state(base_config, conn_with_data):
    return {
        "conn": conn_with_data,
        "config": base_config,
        "symbols": ["sh000001"],
        "analysis_date": date.today().isoformat(),
        "market_assessment": None,
        "fundamentals_assessment": None,
        "risk_assessment": None,
        "final_assessment": None,
    }


# ---- BaseAgent ----

class TestBaseAgent:
    def test_is_abstract(self):
        with pytest.raises(TypeError):
            BaseAgent(None, {})

    def test_concrete_subclass(self, conn, base_config):
        class DummyAgent(BaseAgent):
            @property
            def name(self): return "Dummy"
            def run(self, state): return state

        agent = DummyAgent(conn, base_config)
        assert agent.name == "Dummy"
        result = agent.run({"test": True})
        assert result == {"test": True}


# ---- MarketAnalyst ----

class TestMarketAnalyst:
    def test_with_data(self, state):
        agent = MarketAnalyst(state["conn"], state["config"])
        result = agent.run(state)
        ma = result["market_assessment"]
        assert ma["agent"] == "MarketAnalyst"
        assert "sh000001" in ma["per_symbol"]
        sym_data = ma["per_symbol"]["sh000001"]
        assert sym_data["signal"] in ("bullish", "bearish", "neutral")
        assert -1 <= sym_data["composite_score"] <= 1

    def test_no_data_symbol(self, conn, base_config):
        state = {
            "conn": conn, "config": base_config,
            "symbols": ["nonexistent"],
            "analysis_date": date.today().isoformat(),
            "market_assessment": None, "fundamentals_assessment": None,
            "risk_assessment": None, "final_assessment": None,
        }
        agent = MarketAnalyst(conn, base_config)
        result = agent.run(state)
        sym = result["market_assessment"]["per_symbol"]["nonexistent"]
        assert sym["signal"] == "neutral"
        assert sym["confidence"] == 0.0

    def test_rsi_boundaries(self):
        assert MarketAnalyst._score_rsi(29) == 1.0
        assert MarketAnalyst._score_rsi(31) == 0.3
        assert MarketAnalyst._score_rsi(69) == -0.3
        assert MarketAnalyst._score_rsi(71) == -1.0
        assert MarketAnalyst._score_rsi(None) == 0.0


# ---- FundamentalsAnalyst ----

class TestFundamentalsAnalyst:
    def test_with_data(self, state):
        agent = FundamentalsAnalyst(state["conn"], state["config"])
        result = agent.run(state)
        fa = result["fundamentals_assessment"]
        assert fa["agent"] == "FundamentalsAnalyst"
        sym = fa["per_symbol"]["sh000001"]
        assert sym["pe"] == 15.2
        assert sym["signal"] in ("bullish", "bearish", "neutral")

    def test_no_node_data(self, conn, base_config):
        state = {
            "conn": conn, "config": base_config,
            "symbols": ["sh000001"],
            "analysis_date": date.today().isoformat(),
            "market_assessment": None, "fundamentals_assessment": None,
            "risk_assessment": None, "final_assessment": None,
        }
        agent = FundamentalsAnalyst(conn, base_config)
        result = agent.run(state)
        sym = result["fundamentals_assessment"]["per_symbol"]["sh000001"]
        assert sym["signal"] == "no_data"

    def test_pe_boundaries(self):
        assert FundamentalsAnalyst._score_pe(-1) == -1.0
        assert FundamentalsAnalyst._score_pe(10) == 1.0
        assert FundamentalsAnalyst._score_pe(20) == 0.0
        assert FundamentalsAnalyst._score_pe(30) == -0.5
        assert FundamentalsAnalyst._score_pe(60) == -1.0

    def test_mktcap_classification(self):
        assert FundamentalsAnalyst._classify_mktcap(2_000_000) == "large_cap"
        assert FundamentalsAnalyst._classify_mktcap(500_000) == "mid_cap"
        assert FundamentalsAnalyst._classify_mktcap(50_000) == "small_cap"


# ---- RiskAnalyst ----

class TestRiskAnalyst:
    def test_with_data(self, state):
        agent = RiskAnalyst(state["conn"], state["config"])
        result = agent.run(state)
        ra = result["risk_assessment"]
        assert ra["agent"] == "RiskAnalyst"
        sym = ra["per_symbol"]["sh000001"]
        assert 0 <= sym["risk_score"] <= 1
        assert sym["risk_level"] in ("low", "medium", "high")

    def test_insufficient_history(self, conn, base_config):
        state = {
            "conn": conn, "config": base_config,
            "symbols": ["sh000001"],
            "analysis_date": date.today().isoformat(),
            "market_assessment": None, "fundamentals_assessment": None,
            "risk_assessment": None, "final_assessment": None,
        }
        agent = RiskAnalyst(conn, base_config)
        result = agent.run(state)
        sym = result["risk_assessment"]["per_symbol"]["sh000001"]
        assert sym.get("note") == "insufficient_history"
        assert sym["risk_score"] == 0.5

    def test_max_drawdown(self):
        assert RiskAnalyst._max_drawdown([100, 110, 105, 115, 108]) == pytest.approx(0.0609, abs=0.001)
        assert RiskAnalyst._max_drawdown([100, 100, 100]) == 0.0
        assert RiskAnalyst._max_drawdown([]) == 0.0


# ---- Synthesizer ----

class TestSynthesizer:
    def test_with_all_assessments(self, state):
        # 先运行前三个 agent
        MarketAnalyst(state["conn"], state["config"]).run(state)
        FundamentalsAnalyst(state["conn"], state["config"]).run(state)
        RiskAnalyst(state["conn"], state["config"]).run(state)

        agent = Synthesizer(state["conn"], state["config"])
        result = agent.run(state)
        fa = result["final_assessment"]
        assert fa["agent"] == "Synthesizer"
        sym = fa["per_symbol"]["sh000001"]
        assert sym["recommendation"] in ("BUY", "HOLD", "SELL")
        assert -1 <= sym["final_score"] <= 1

    def test_with_no_assessments(self, conn, base_config):
        state = {
            "conn": conn, "config": base_config,
            "symbols": ["sh000001"],
            "analysis_date": date.today().isoformat(),
            "market_assessment": None, "fundamentals_assessment": None,
            "risk_assessment": None, "final_assessment": None,
        }
        agent = Synthesizer(conn, base_config)
        result = agent.run(state)
        sym = result["final_assessment"]["per_symbol"]["sh000001"]
        assert sym["recommendation"] == "HOLD"
        assert sym["final_score"] == pytest.approx(0.15, abs=0.01)  # (1-0.5)*0.3


# ---- AnalysisPipeline ----

class TestAnalysisPipeline:
    def test_full_pipeline(self, conn_with_data, base_config):
        pipeline = AnalysisPipeline(conn_with_data, base_config)
        state = pipeline.run(symbols=["sh000001"])
        assert state["market_assessment"] is not None
        assert state["fundamentals_assessment"] is not None
        assert state["risk_assessment"] is not None
        assert state["final_assessment"] is not None

    def test_format_report(self, conn_with_data, base_config):
        pipeline = AnalysisPipeline(conn_with_data, base_config)
        state = pipeline.run(symbols=["sh000001"])
        report = pipeline.format_report(state)
        assert "多智能体分析报告" in report
        assert "sh000001" in report
        assert "BUY" in report or "HOLD" in report or "SELL" in report


# ---- format_analysis_report ----

class TestFormatReport:
    def test_empty_state(self):
        report = format_analysis_report({"analysis_date": "2026-01-01"})
        assert "无分析结果" in report


# ---- ProjectScorer ----

class TestProjectScorer:
    def test_score_returns_structure(self):
        scorer = ProjectScorer()
        result = scorer.score()
        assert "total" in result
        assert "breakdown" in result
        assert "eligible" in result
        assert result["total"] >= 0

    def test_threshold(self):
        assert ProjectScorer.THRESHOLD == 90

    def test_module_count(self):
        scorer = ProjectScorer()
        score = scorer.score_module_count()
        assert score > 0  # 项目应有模块

    def test_config_validation(self):
        scorer = ProjectScorer()
        score = scorer.score_config_validation()
        assert score == 5  # config.yaml 存在且合法

    def test_docstring_coverage(self):
        scorer = ProjectScorer()
        score = scorer.score_docstring_coverage()
        assert score >= 0
