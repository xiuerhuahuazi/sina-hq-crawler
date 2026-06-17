"""Synthesizer — 综合三个分析师的报告，产出最终评估。"""

from src.agents.base import BaseAgent


# 评分权重
_WEIGHTS = {
    "market": 0.4,
    "fundamentals": 0.3,
    "risk": 0.3,
}


class Synthesizer(BaseAgent):
    """综合市场、基本面、风险评估，产出 BUY/HOLD/SELL 建议。"""

    @property
    def name(self) -> str:
        return "Synthesizer"

    def run(self, state: dict) -> dict:
        symbols = state["symbols"]
        market = state.get("market_assessment") or {}
        fundamentals = state.get("fundamentals_assessment") or {}
        risk = state.get("risk_assessment") or {}

        market_ps = market.get("per_symbol", {})
        fund_ps = fundamentals.get("per_symbol", {})
        risk_ps = risk.get("per_symbol", {})

        per_symbol = {}
        for sym in symbols:
            per_symbol[sym] = self._synthesize(
                sym,
                market_ps.get(sym),
                fund_ps.get(sym),
                risk_ps.get(sym),
            )

        buy_count = sum(1 for v in per_symbol.values() if v["recommendation"] == "BUY")
        hold_count = sum(1 for v in per_symbol.values() if v["recommendation"] == "HOLD")
        sell_count = sum(1 for v in per_symbol.values() if v["recommendation"] == "SELL")

        assessment = {
            "agent": self.name,
            "timestamp": self._timestamp(),
            "per_symbol": per_symbol,
            "overall_summary": (
                f"{len(symbols)} symbols analyzed: "
                f"{buy_count} BUY, {hold_count} HOLD, {sell_count} SELL"
            ),
        }
        state["final_assessment"] = assessment
        return state

    def _synthesize(self, symbol: str, market: dict | None, fund: dict | None, risk: dict | None) -> dict:
        """综合三个评估产出最终建议。"""
        market_score = (market or {}).get("composite_score", 0.0)
        fund_score = (fund or {}).get("composite_score", 0.0)
        risk_score = (risk or {}).get("risk_score", 0.5)

        # 风险取反：低风险 = 正面
        risk_inverted = 1.0 - risk_score

        # 加权合成
        final_score = (
            market_score * _WEIGHTS["market"]
            + fund_score * _WEIGHTS["fundamentals"]
            + risk_inverted * _WEIGHTS["risk"]
        )
        final_score = max(-1.0, min(1.0, final_score))

        # 有效评估数量（用于置信度调整）
        valid_count = 0
        if market and market.get("signal") not in (None, "no_data"):
            valid_count += 1
        if fund and fund.get("signal") not in (None, "no_data"):
            valid_count += 1
        if risk and risk.get("risk_score") is not None:
            valid_count += 1

        confidence = abs(final_score)
        if valid_count < 3:
            confidence *= valid_count / 3.0

        recommendation = "BUY" if final_score > 0.3 else ("SELL" if final_score < -0.3 else "HOLD")

        # 生成理由
        rationale = self._build_rationale(market, fund, risk, recommendation)

        return {
            "market_score": round(market_score, 4),
            "fundamentals_score": round(fund_score, 4),
            "risk_score": round(risk_score, 4),
            "risk_inverted": round(risk_inverted, 4),
            "final_score": round(final_score, 4),
            "recommendation": recommendation,
            "confidence": round(confidence, 4),
            "rationale": rationale,
        }

    @staticmethod
    def _build_rationale(market: dict | None, fund: dict | None, risk: dict | None, rec: str) -> str:
        parts = []
        m_signal = (market or {}).get("signal", "no data")
        f_signal = (fund or {}).get("signal", "no data")
        r_level = (risk or {}).get("risk_level", "unknown")

        parts.append(f"Technical: {m_signal}")
        parts.append(f"Fundamentals: {f_signal}")
        parts.append(f"Risk: {r_level}")

        if rec == "BUY":
            parts.insert(0, "Bullish outlook based on")
        elif rec == "SELL":
            parts.insert(0, "Bearish outlook based on")
        else:
            parts.insert(0, "Mixed signals from")

        return ", ".join(parts[:2]) + " and " + parts[2] if len(parts) > 2 else ", ".join(parts)


def format_analysis_report(state: dict) -> str:
    """将分析状态渲染为 Markdown 报告。"""
    lines = []
    lines.append("# 多智能体分析报告\n")
    lines.append(f"**分析日期**: {state.get('analysis_date', 'N/A')}\n")

    final = state.get("final_assessment")
    if not final:
        lines.append("无分析结果。\n")
        return "\n".join(lines)

    lines.append(f"**{final.get('overall_summary', '')}**\n")

    for sym, data in final.get("per_symbol", {}).items():
        lines.append(f"## {sym}\n")
        lines.append("| 指标 | 值 |")
        lines.append("|------|------|")
        lines.append(f"| 综合评分 | {data['final_score']:.4f} |")
        lines.append(f"| 建议 | **{data['recommendation']}** |")
        lines.append(f"| 置信度 | {data['confidence']:.4f} |")
        lines.append(f"| 技术评分 | {data['market_score']:.4f} |")
        lines.append(f"| 基本面评分 | {data['fundamentals_score']:.4f} |")
        lines.append(f"| 风险评分 | {data['risk_score']:.4f} |")
        lines.append(f"| 理由 | {data.get('rationale', '')} |")
        lines.append("")

    return "\n".join(lines)
