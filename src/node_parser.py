"""节点数据解析器 — 解析 getHQNodeData API 返回的 JSON。"""

import logging

logger = logging.getLogger(__name__)


def _safe_float(val) -> float | None:
    """安全转换为 float，失败返回 None。零值保留（停牌volume=0、平盘pricechange=0 有意义）。"""
    if val is None or val == "" or val == "-":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def parse_node_data(items: list[dict]) -> list[dict]:
    """解析节点数据列表，提取标准化字段。

    返回 list[dict]，每个 dict 包含:
        symbol, code, name, trade, pricechange, changepercent,
        buy, sell, settlement, open, high, low, volume, amount,
        ticktime, per, pb, mktcap, nmc, turnoverratio
    """
    result = []
    for item in items:
        symbol = item.get("symbol", "")
        if not symbol:
            continue
        result.append({
            "symbol": symbol,
            "code": item.get("code", ""),
            "name": item.get("name", ""),
            "trade": _safe_float(item.get("trade")),
            "pricechange": _safe_float(item.get("pricechange")),
            "changepercent": _safe_float(item.get("changepercent")),
            "buy": _safe_float(item.get("buy")),
            "sell": _safe_float(item.get("sell")),
            "settlement": _safe_float(item.get("settlement")),
            "open": _safe_float(item.get("open")),
            "high": _safe_float(item.get("high")),
            "low": _safe_float(item.get("low")),
            "volume": _safe_float(item.get("volume")),
            "amount": _safe_float(item.get("amount")),
            "ticktime": item.get("ticktime", ""),
            "per": _safe_float(item.get("per")),
            "pb": _safe_float(item.get("pb")),
            "mktcap": _safe_float(item.get("mktcap")),
            "nmc": _safe_float(item.get("nmc")),
            "turnoverratio": _safe_float(item.get("turnoverratio")),
        })
    return result
