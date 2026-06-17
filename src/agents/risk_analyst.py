"""RiskAnalyst — 波动率、回撤、流动性风险评估。"""

import math
from src.agents.base import BaseAgent


class RiskAnalyst(BaseAgent):
    """量化风险评估（波动率、回撤、ATR、流动性）。"""

    @property
    def name(self) -> str:
        return "RiskAnalyst"

    def run(self, state: dict) -> dict:
        conn = state["conn"]
        symbols = state["symbols"]

        per_symbol = {}
        for sym in symbols:
            try:
                per_symbol[sym] = self._analyze_symbol(conn, sym)
            except Exception as e:
                self._logger.warning("RiskAnalyst 分析 %s 失败: %s", sym, e)
                per_symbol[sym] = self._unknown_result()

        risk_scores = [v["risk_score"] for v in per_symbol.values() if v.get("risk_score") is not None]
        avg_risk = sum(risk_scores) / len(risk_scores) if risk_scores else 0.5

        assessment = {
            "agent": self.name,
            "timestamp": self._timestamp(),
            "per_symbol": per_symbol,
            "risk_summary": f"Average risk score: {avg_risk:.2f} ({self._risk_level(avg_risk)})",
        }
        state["risk_assessment"] = assessment
        return state

    def _analyze_symbol(self, conn, symbol: str) -> dict:
        # 获取日线数据
        rows = conn.execute(
            "SELECT close, volume, amount FROM dws_daily_summary "
            "WHERE symbol = ? ORDER BY trade_date", (symbol,)
        ).fetchall()

        if len(rows) < 2:
            result = self._unknown_result()
            result["note"] = "insufficient_history"
            return result

        closes = [r[0] for r in rows if r[0] is not None]
        amounts = [r[2] for r in rows if r[2] is not None]

        if len(closes) < 2:
            return self._unknown_result()

        # 日收益率
        returns = [(closes[i] / closes[i-1] - 1) for i in range(1, len(closes)) if closes[i-1] and closes[i-1] > 0]

        # 波动率
        vol = self._stddev(returns)
        annualized_vol = vol * math.sqrt(250) if vol else 0.0

        # 最大回撤
        max_dd = self._max_drawdown(closes)

        # ATR
        atr_data = self._compute_atr(conn, symbol)
        current_price = closes[-1] if closes else None
        atr_pct = (atr_data / current_price) if (atr_data and current_price and current_price > 0) else None

        # 流动性
        avg_amount = sum(amounts) / len(amounts) if amounts else 0

        # 风险评分
        vol_score = self._categorize_vol(annualized_vol)
        dd_score = self._categorize_drawdown(max_dd)
        atr_score = self._categorize_atr(atr_pct)

        risk_score = (vol_score + dd_score + atr_score) / 3

        return {
            "annualized_volatility": round(annualized_vol, 4),
            "volatility_category": self._vol_category(annualized_vol),
            "max_drawdown": round(max_dd, 4),
            "drawdown_category": self._dd_category(max_dd),
            "atr_pct": round(atr_pct, 4) if atr_pct else None,
            "atr_category": self._atr_category(atr_pct),
            "avg_daily_amount": round(avg_amount, 2),
            "liquidity_category": self._liquidity_category(avg_amount),
            "risk_score": round(risk_score, 4),
            "risk_level": self._risk_level(risk_score),
        }

    def _compute_atr(self, conn, symbol: str) -> float | None:
        """从日线数据计算 ATR(14)。"""
        rows = conn.execute(
            "SELECT high, low, close FROM dws_daily_summary "
            "WHERE symbol = ? ORDER BY trade_date DESC LIMIT 15", (symbol,)
        ).fetchall()
        if len(rows) < 2:
            return None
        rows = list(reversed(rows))
        tr_list = []
        for i in range(1, len(rows)):
            hi, lo, pc = rows[i][0], rows[i][1], rows[i-1][2]
            if hi and lo and pc:
                tr = max(hi - lo, abs(hi - pc), abs(lo - pc))
                tr_list.append(tr)
        if not tr_list:
            return None
        return sum(tr_list[-14:]) / len(tr_list[-14:])

    @staticmethod
    def _stddev(values: list[float]) -> float:
        if len(values) < 2:
            return 0.0
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / (len(values) - 1)
        return math.sqrt(variance)

    @staticmethod
    def _max_drawdown(closes: list[float]) -> float:
        if not closes:
            return 0.0
        peak = closes[0]
        max_dd = 0.0
        for c in closes:
            if c > peak:
                peak = c
            dd = (peak - c) / peak if peak > 0 else 0
            max_dd = max(max_dd, dd)
        return max_dd

    @staticmethod
    def _categorize_vol(vol: float) -> float:
        if vol < 0.15:
            return 0.25
        if vol < 0.30:
            return 0.5
        return 0.75

    @staticmethod
    def _categorize_drawdown(dd: float) -> float:
        if dd < 0.05:
            return 0.25
        if dd < 0.15:
            return 0.5
        return 0.75

    @staticmethod
    def _categorize_atr(atr_pct: float | None) -> float:
        if atr_pct is None:
            return 0.5
        if atr_pct < 0.02:
            return 0.25
        if atr_pct < 0.04:
            return 0.5
        return 0.75

    @staticmethod
    def _vol_category(vol: float) -> str:
        if vol < 0.15:
            return "low_vol"
        if vol < 0.30:
            return "medium_vol"
        return "high_vol"

    @staticmethod
    def _dd_category(dd: float) -> str:
        if dd < 0.05:
            return "low_drawdown"
        if dd < 0.15:
            return "moderate_drawdown"
        return "severe_drawdown"

    @staticmethod
    def _atr_category(atr_pct: float | None) -> str:
        if atr_pct is None:
            return "unknown"
        if atr_pct < 0.02:
            return "low"
        if atr_pct < 0.04:
            return "medium"
        return "high"

    @staticmethod
    def _liquidity_category(avg_amount: float) -> str:
        if avg_amount < 1e6:
            return "illiquid"
        if avg_amount < 1e8:
            return "normal"
        return "liquid"

    @staticmethod
    def _risk_level(score: float) -> str:
        if score < 0.35:
            return "low"
        if score < 0.60:
            return "medium"
        return "high"

    @staticmethod
    def _unknown_result() -> dict:
        return {
            "annualized_volatility": None,
            "volatility_category": "unknown",
            "max_drawdown": None,
            "drawdown_category": "unknown",
            "atr_pct": None,
            "atr_category": "unknown",
            "avg_daily_amount": None,
            "liquidity_category": "unknown",
            "risk_score": 0.5,
            "risk_level": "medium",
        }
