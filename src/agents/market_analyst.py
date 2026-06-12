"""MarketAnalyst — 技术指标分析，产出方向性信号。"""

from src.agents.base import BaseAgent
from src.indicators import compute_latest


# 指标权重
_WEIGHTS = {
    "rsi": 0.2,
    "macd": 0.2,
    "ma": 0.2,
    "boll": 0.1,
    "kdj": 0.1,
    "vwap": 0.1,
    "volume_ratio": 0.1,
}


class MarketAnalyst(BaseAgent):
    """基于技术指标的市场方向分析。"""

    @property
    def name(self) -> str:
        return "MarketAnalyst"

    def run(self, state: dict) -> dict:
        conn = state["conn"]
        symbols = state["symbols"]

        per_symbol = {}
        for sym in symbols:
            try:
                per_symbol[sym] = self._analyze_symbol(conn, sym)
            except Exception as e:
                self._logger.warning("MarketAnalyst 分析 %s 失败: %s", sym, e)
                per_symbol[sym] = self._empty_result(str(e))

        # 统计信号分布
        signals = [v["signal"] for v in per_symbol.values()]
        bullish = signals.count("bullish")
        bearish = signals.count("bearish")
        neutral = signals.count("neutral")

        assessment = {
            "agent": self.name,
            "timestamp": self._timestamp(),
            "per_symbol": per_symbol,
            "market_summary": f"{bullish} bullish, {bearish} bearish, {neutral} neutral out of {len(signals)} symbols",
        }
        state["market_assessment"] = assessment
        return state

    def _analyze_symbol(self, conn, symbol: str) -> dict:
        """分析单个标的的技术指标。"""
        data = compute_latest(conn, symbol)
        if data.get("rsi14") is None and data.get("macd_dif") is None:
            return self._empty_result("insufficient_data")

        scores = {}
        # RSI
        rsi = data.get("rsi14")
        scores["rsi"] = self._score_rsi(rsi)

        # MACD
        dif = data.get("macd_dif")
        dea = data.get("macd_dea")
        bar = data.get("macd_bar")
        scores["macd"] = self._score_macd(dif, dea, bar)

        # MA crossover
        close = data.get("vwap")  # 近似当前价
        ma5 = data.get("ma5")
        ma10 = data.get("ma10")
        ma20 = data.get("ma20")
        scores["ma"] = self._score_ma(close, ma5, ma10, ma20)

        # Bollinger
        boll_upper = data.get("boll_upper")
        boll_lower = data.get("boll_lower")
        boll_mid = data.get("boll_mid")
        scores["boll"] = self._score_boll(close, boll_upper, boll_lower, boll_mid)

        # KDJ
        kdj_j = data.get("kdj_j")
        scores["kdj"] = self._score_kdj(kdj_j)

        # VWAP
        vwap = data.get("vwap")
        scores["vwap"] = self._score_vwap(close, vwap)

        # Volume ratio
        vol_ratio = data.get("volume_ratio")
        scores["volume_ratio"] = 0.0  # 不直接得分，用于调整

        # 加权合成
        composite = 0.0
        total_weight = 0.0
        for key, weight in _WEIGHTS.items():
            if key in scores and scores[key] is not None:
                composite += scores[key] * weight
                total_weight += weight

        if total_weight > 0:
            composite /= total_weight

        # 量比调整
        if vol_ratio is not None:
            if vol_ratio > 2.0:
                composite *= 1.3
            elif vol_ratio < 0.5:
                composite *= 0.7
        composite = max(-1.0, min(1.0, composite))

        signal = "bullish" if composite > 0.2 else ("bearish" if composite < -0.2 else "neutral")

        return {
            "indicators": data,
            "scores": scores,
            "composite_score": round(composite, 4),
            "signal": signal,
            "confidence": round(abs(composite), 4),
        }

    @staticmethod
    def _score_rsi(rsi: float | None) -> float:
        if rsi is None:
            return 0.0
        if rsi < 30:
            return 1.0
        if rsi < 50:
            return 0.3
        if rsi < 70:
            return -0.3
        return -1.0

    @staticmethod
    def _score_macd(dif, dea, bar) -> float:
        if dif is None or dea is None:
            return 0.0
        if dif > dea and (bar is not None and bar > 0):
            return 1.0
        if dif < dea and (bar is not None and bar < 0):
            return -1.0
        return 0.0

    @staticmethod
    def _score_ma(close, ma5, ma10, ma20) -> float:
        if any(v is None for v in [close, ma5, ma10, ma20]):
            return 0.0
        if close > ma5 > ma10 > ma20:
            return 1.0
        if close < ma5 < ma10 < ma20:
            return -1.0
        if close > ma5:
            return 0.3
        if close < ma5:
            return -0.3
        return 0.0

    @staticmethod
    def _score_boll(close, upper, lower, mid) -> float:
        if any(v is None for v in [close, upper, lower]):
            return 0.0
        if close < lower:
            return 1.0
        if close > upper:
            return -1.0
        if mid and close > mid:
            return -0.3
        if mid and close < mid:
            return 0.3
        return 0.0

    @staticmethod
    def _score_kdj(j) -> float:
        if j is None:
            return 0.0
        if j > 100:
            return -1.0
        if j < 0:
            return 1.0
        return 0.0

    @staticmethod
    def _score_vwap(close, vwap) -> float:
        if close is None or vwap is None:
            return 0.0
        return 0.5 if close > vwap else -0.5

    @staticmethod
    def _empty_result(reason: str) -> dict:
        return {
            "indicators": {},
            "scores": {},
            "composite_score": 0.0,
            "signal": "neutral",
            "confidence": 0.0,
            "note": reason,
        }
