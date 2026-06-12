"""FundamentalsAnalyst — 估值指标分析（PE/PB/市值/换手率）。"""

from src.agents.base import BaseAgent


class FundamentalsAnalyst(BaseAgent):
    """基于基本面指标的估值分析。"""

    @property
    def name(self) -> str:
        return "FundamentalsAnalyst"

    def run(self, state: dict) -> dict:
        conn = state["conn"]
        symbols = state["symbols"]

        per_symbol = {}
        for sym in symbols:
            try:
                per_symbol[sym] = self._analyze_symbol(conn, sym)
            except Exception as e:
                self._logger.warning("FundamentalsAnalyst 分析 %s 失败: %s", sym, e)
                per_symbol[sym] = self._no_data_result(str(e))

        analyzed = sum(1 for v in per_symbol.values() if v["signal"] != "no_data")
        no_data = sum(1 for v in per_symbol.values() if v["signal"] == "no_data")

        assessment = {
            "agent": self.name,
            "timestamp": self._timestamp(),
            "per_symbol": per_symbol,
            "fundamentals_summary": f"{analyzed} analyzed, {no_data} no data out of {len(symbols)} symbols",
        }
        state["fundamentals_assessment"] = assessment
        return state

    def _analyze_symbol(self, conn, symbol: str) -> dict:
        row = conn.execute(
            "SELECT per, pb, mktcap, nmc, turnoverratio FROM dwd_node_data WHERE symbol = ?",
            (symbol,)
        ).fetchone()

        if row is None:
            return self._no_data_result("no node data")

        pe, pb, mktcap, nmc, turnover = row

        # 行业信息
        industry_code = None
        industry_name = None
        ind_row = conn.execute(
            "SELECT classification_code FROM dim_symbol_classifications "
            "WHERE symbol = ? AND classification_type = 'sw_industry'",
            (symbol,)
        ).fetchone()
        if ind_row:
            industry_code = ind_row[0]
            name_row = conn.execute(
                "SELECT name FROM dim_industries WHERE code = ?", (industry_code,)
            ).fetchone()
            if name_row:
                industry_name = name_row[0]

        # 评分
        scores = {}
        scores["pe"] = self._score_pe(pe)
        scores["pb"] = self._score_pb(pb)
        scores["turnover"] = self._score_turnover(turnover)

        composite = scores["pe"] * 0.4 + scores["pb"] * 0.3 + scores["turnover"] * 0.3

        signal = "bullish" if composite > 0.2 else ("bearish" if composite < -0.2 else "neutral")

        return {
            "pe": pe, "pb": pb,
            "mktcap": mktcap, "circ_mktcap": nmc,
            "turnover_ratio": turnover,
            "industry": industry_code,
            "industry_name": industry_name,
            "market_cap_class": self._classify_mktcap(mktcap),
            "scores": scores,
            "composite_score": round(composite, 4),
            "signal": signal,
            "confidence": round(abs(composite), 4),
        }

    @staticmethod
    def _score_pe(pe) -> float:
        if pe is None:
            return 0.0
        if pe < 0:
            return -1.0
        if pe < 15:
            return 1.0
        if pe < 25:
            return 0.0
        if pe < 50:
            return -0.5
        return -1.0

    @staticmethod
    def _score_pb(pb) -> float:
        if pb is None:
            return 0.0
        if pb < 1:
            return 1.0
        if pb < 3:
            return 0.0
        return -0.5

    @staticmethod
    def _score_turnover(turnover) -> float:
        if turnover is None:
            return 0.0
        if turnover > 10:
            return 0.5
        if turnover > 3:
            return 0.0
        if turnover < 1:
            return -0.3
        return 0.0

    @staticmethod
    def _classify_mktcap(mktcap) -> str:
        if mktcap is None:
            return "unknown"
        # mktcap 单位为万元
        if mktcap > 1_000_000:  # > 100亿
            return "large_cap"
        if mktcap > 100_000:  # > 10亿
            return "mid_cap"
        return "small_cap"

    @staticmethod
    def _no_data_result(reason: str) -> dict:
        return {
            "pe": None, "pb": None,
            "mktcap": None, "circ_mktcap": None,
            "turnover_ratio": None,
            "industry": None, "industry_name": None,
            "market_cap_class": "unknown",
            "scores": {},
            "composite_score": 0.0,
            "signal": "no_data",
            "confidence": 0.0,
            "note": reason,
        }
