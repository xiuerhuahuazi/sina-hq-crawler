"""技术指标计算模块 — 盘中实时 + 离线历史。"""

import json
import logging
import sqlite3
from datetime import date

logger = logging.getLogger(__name__)


# ============================================================================
# 盘中实时指标（基于当日分钟K线和 tick 数据）
# ============================================================================

def intraday_vwap(conn: sqlite3.Connection, symbol: str,
                  trade_date: str | None = None) -> float | None:
    """当日 VWAP（成交量加权平均价）。

    VWAP = SUM(close * volume) / SUM(volume)
    使用分钟K线的 amount / volume 计算。
    """
    if trade_date is None:
        trade_date = date.today().isoformat()
    row = conn.execute("""
        SELECT SUM(amount), SUM(volume)
        FROM dws_minute_bars
        WHERE symbol = ?
          AND bar_minute LIKE ?
    """, (symbol, f"{trade_date}%")).fetchone()
    if row and row[0] and row[1] and row[1] > 0:
        return row[0] / row[1]
    return None


def intraday_volume_ratio(conn: sqlite3.Connection, symbol: str,
                          lookback: int = 5,
                          trade_date: str | None = None) -> float | None:
    """量比：最新一分钟成交量 / 前 N 分钟平均成交量。

    量比 > 2 通常表示异常放量。
    """
    if trade_date is None:
        trade_date = date.today().isoformat()
    rows = conn.execute("""
        SELECT volume
        FROM dws_minute_bars
        WHERE symbol = ?
          AND bar_minute LIKE ?
          AND volume > 0
        ORDER BY bar_minute DESC
        LIMIT ?
    """, (symbol, f"{trade_date}%", lookback + 1)).fetchall()
    if len(rows) < 2:
        return None
    latest = rows[0][0]
    avg_prev = sum(r[0] for r in rows[1:]) / len(rows[1:])
    if avg_prev > 0:
        return latest / avg_prev
    return None


def intraday_orderbook_spread(conn: sqlite3.Connection, symbol: str) -> dict | None:
    """买卖价差：从最新 order_book 计算 bid-ask spread。"""
    row = conn.execute("""
        SELECT order_book
        FROM dwd_quotes
        WHERE symbol = ? AND order_book IS NOT NULL
        ORDER BY fetched_at DESC
        LIMIT 1
    """, (symbol,)).fetchone()
    if not row or not row[0]:
        return None
    try:
        ob = json.loads(row[0])
    except (json.JSONDecodeError, TypeError):
        return None
    bid0 = ob.get("bid", [{}])[0].get("p", 0)
    ask0 = ob.get("ask", [{}])[0].get("p", 0)
    if bid0 and ask0 and bid0 > 0 and ask0 > 0:
        spread = ask0 - bid0
        mid = (ask0 + bid0) / 2
        return {
            "bid0": bid0,
            "ask0": ask0,
            "spread": round(spread, 4),
            "spread_pct": round(spread / mid * 100, 4),
        }
    return None


def intraday_orderbook_imbalance(conn: sqlite3.Connection, symbol: str) -> dict | None:
    """盘口挂单比：bid 总挂单量 / ask 总挂单量。"""
    row = conn.execute("""
        SELECT order_book
        FROM dwd_quotes
        WHERE symbol = ? AND order_book IS NOT NULL
        ORDER BY fetched_at DESC
        LIMIT 1
    """, (symbol,)).fetchone()
    if not row or not row[0]:
        return None
    try:
        ob = json.loads(row[0])
    except (json.JSONDecodeError, TypeError):
        return None
    bid_total = sum(level.get("v", 0) for level in ob.get("bid", []))
    ask_total = sum(level.get("v", 0) for level in ob.get("ask", []))
    if bid_total > 0 and ask_total > 0:
        return {
            "bid_total": bid_total,
            "ask_total": ask_total,
            "ratio": round(bid_total / ask_total, 4),
            "bias": "bid" if bid_total > ask_total else "ask",
        }
    return None


def intraday_cumulative_volume(conn: sqlite3.Connection, symbol: str,
                               trade_date: str | None = None) -> float | None:
    """当日累计成交量（从分钟K线聚合）。"""
    if trade_date is None:
        trade_date = date.today().isoformat()
    row = conn.execute("""
        SELECT SUM(volume)
        FROM dws_minute_bars
        WHERE symbol = ?
          AND bar_minute LIKE ?
    """, (symbol, f"{trade_date}%")).fetchone()
    if row and row[0]:
        return row[0]
    return None


# ============================================================================
# 离线历史指标（基于 dws_daily_summary 多日数据）
# ============================================================================

def _fetch_daily_closes(conn: sqlite3.Connection, symbol: str,
                        period: int = 30) -> list[dict]:
    """从日终汇总表获取最近 N 个交易日数据。"""
    rows = conn.execute("""
        SELECT trade_date, open, high, low, close, volume, amount, prev_close
        FROM dws_daily_summary
        WHERE symbol = ?
        ORDER BY trade_date DESC
        LIMIT ?
    """, (symbol, period)).fetchall()
    if not rows:
        return []
    # 反转为时间正序
    return [
        {
            "trade_date": r[0], "open": r[1], "high": r[2], "low": r[3],
            "close": r[4], "volume": r[5], "amount": r[6], "prev_close": r[7],
        }
        for r in reversed(rows)
    ]


def _closes(data: list[dict]) -> list[float]:
    """提取 close 序列。"""
    return [d["close"] for d in data if d["close"] is not None]


def daily_ma(conn: sqlite3.Connection, symbol: str,
             window: int = 20, period: int = 60) -> list[dict]:
    """简单移动平均。返回 [{trade_date, close, ma}, ...]。"""
    data = _fetch_daily_closes(conn, symbol, period)
    if len(data) < window:
        return []
    closes = _closes(data)
    result = []
    for i in range(len(data)):
        if i < window - 1:
            result.append({"trade_date": data[i]["trade_date"],
                           "close": data[i]["close"], "ma": None})
        else:
            window_avg = sum(closes[i - window + 1:i + 1]) / window
            result.append({"trade_date": data[i]["trade_date"],
                           "close": data[i]["close"],
                           "ma": round(window_avg, 4)})
    return result


def daily_ema(conn: sqlite3.Connection, symbol: str,
              window: int = 20, period: int = 60) -> list[dict]:
    """指数移动平均。返回 [{trade_date, close, ema}, ...]。"""
    data = _fetch_daily_closes(conn, symbol, period)
    if len(data) < window:
        return []
    closes = _closes(data)
    k = 2.0 / (window + 1)
    result = []
    ema_val = None
    for i, c in enumerate(closes):
        if i < window - 1:
            result.append({"trade_date": data[i]["trade_date"],
                           "close": data[i]["close"], "ema": None})
        elif i == window - 1:
            ema_val = sum(closes[:window]) / window
            result.append({"trade_date": data[i]["trade_date"],
                           "close": data[i]["close"],
                           "ema": round(ema_val, 4)})
        else:
            ema_val = c * k + ema_val * (1 - k)
            result.append({"trade_date": data[i]["trade_date"],
                           "close": data[i]["close"],
                           "ema": round(ema_val, 4)})
    return result


def daily_macd(conn: sqlite3.Connection, symbol: str,
               fast: int = 12, slow: int = 26, signal: int = 9,
               period: int = 60) -> list[dict]:
    """MACD 指标。返回 [{trade_date, dif, dea, macd}, ...]。"""
    data = _fetch_daily_closes(conn, symbol, period)
    if len(data) < slow:
        return []
    closes = _closes(data)

    # 计算 EMA
    def ema_series(values, window):
        k = 2.0 / (window + 1)
        result = [None] * (window - 1)
        result.append(sum(values[:window]) / window)
        for i in range(window, len(values)):
            result.append(values[i] * k + result[-1] * (1 - k))
        return result

    ema_fast = ema_series(closes, fast)
    ema_slow = ema_series(closes, slow)

    # DIF = EMA_fast - EMA_slow
    dif = [None if a is None or b is None else round(a - b, 4)
           for a, b in zip(ema_fast, ema_slow)]

    # DEA = EMA(DIF, signal)
    dif_valid = [d for d in dif if d is not None]
    if len(dif_valid) < signal:
        return []

    dea = [None] * len(dif)
    first_valid = next(i for i, d in enumerate(dif) if d is not None)
    dea_start = first_valid + signal - 1
    if dea_start >= len(dif):
        return []

    dea[dea_start] = sum(dif_valid[:signal]) / signal
    k = 2.0 / (signal + 1)
    for i in range(dea_start + 1, len(dif)):
        if dif[i] is not None and dea[i - 1] is not None:
            dea[i] = round(dif[i] * k + dea[i - 1] * (1 - k), 4)

    # MACD 柱 = 2 * (DIF - DEA)
    result = []
    for i, d in enumerate(data):
        macd_bar = None
        if dif[i] is not None and dea[i] is not None:
            macd_bar = round(2 * (dif[i] - dea[i]), 4)
        result.append({
            "trade_date": d["trade_date"],
            "dif": dif[i],
            "dea": dea[i],
            "macd": macd_bar,
        })
    return result


def daily_rsi(conn: sqlite3.Connection, symbol: str,
              window: int = 14, period: int = 30) -> list[dict]:
    """RSI 相对强弱指标。返回 [{trade_date, rsi}, ...]。"""
    data = _fetch_daily_closes(conn, symbol, period)
    if len(data) < window + 1:
        return []
    closes = _closes(data)
    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]

    result = [{"trade_date": data[0]["trade_date"], "rsi": None}]
    if len(changes) < window:
        return result

    gains = [max(c, 0) for c in changes[:window]]
    losses = [abs(min(c, 0)) for c in changes[:window]]
    avg_gain = sum(gains) / window
    avg_loss = sum(losses) / window

    # 前 window 个 RSI 为 None
    for _ in range(window - 1):
        result.append({"trade_date": data[len(result)]["trade_date"], "rsi": None})

    # 第 window 个 RSI
    if avg_loss == 0:
        result.append({"trade_date": data[window]["trade_date"], "rsi": 100.0})
    else:
        rs = avg_gain / avg_loss
        result.append({"trade_date": data[window]["trade_date"],
                       "rsi": round(100 - 100 / (1 + rs), 2)})

    # 后续 RSI（Wilder 平滑）
    for i in range(window, len(changes)):
        gain = max(changes[i], 0)
        loss = abs(min(changes[i], 0))
        avg_gain = (avg_gain * (window - 1) + gain) / window
        avg_loss = (avg_loss * (window - 1) + loss) / window
        if avg_loss == 0:
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = round(100 - 100 / (1 + rs), 2)
        result.append({"trade_date": data[i + 1]["trade_date"], "rsi": rsi})

    return result


def daily_boll(conn: sqlite3.Connection, symbol: str,
               window: int = 20, num_std: float = 2.0,
               period: int = 60) -> list[dict]:
    """布林带。返回 [{trade_date, mid, upper, lower}, ...]。"""
    data = _fetch_daily_closes(conn, symbol, period)
    if len(data) < window:
        return []
    closes = _closes(data)
    result = []
    for i in range(len(data)):
        if i < window - 1:
            result.append({"trade_date": data[i]["trade_date"],
                           "mid": None, "upper": None, "lower": None})
        else:
            window_data = closes[i - window + 1:i + 1]
            mid = sum(window_data) / window
            variance = sum((x - mid) ** 2 for x in window_data) / window
            std = variance ** 0.5
            result.append({
                "trade_date": data[i]["trade_date"],
                "mid": round(mid, 4),
                "upper": round(mid + num_std * std, 4),
                "lower": round(mid - num_std * std, 4),
            })
    return result


def daily_atr(conn: sqlite3.Connection, symbol: str,
              window: int = 14, period: int = 30) -> list[dict]:
    """ATR 平均真实波幅。返回 [{trade_date, atr}, ...]。"""
    data = _fetch_daily_closes(conn, symbol, period)
    if len(data) < 2:
        return []

    # 计算 True Range
    tr_list = []
    for i in range(1, len(data)):
        hi, lo, prev_c = data[i]["high"], data[i]["low"], data[i - 1]["close"]
        if hi is None or lo is None or prev_c is None:
            tr_list.append(None)
            continue
        tr = max(hi - lo, abs(hi - prev_c), abs(lo - prev_c))
        tr_list.append(tr)

    result = [{"trade_date": data[0]["trade_date"], "atr": None}]
    if len(tr_list) < window:
        for _ in range(len(tr_list)):
            result.append({"trade_date": data[len(result)]["trade_date"], "atr": None})
        return result

    # 前 window-1 个为 None
    for i in range(window - 1):
        result.append({"trade_date": data[i + 1]["trade_date"], "atr": None})

    # 第一个 ATR = 简单平均
    valid_trs = [t for t in tr_list[:window] if t is not None]
    if not valid_trs:
        return result
    atr_val = sum(valid_trs) / len(valid_trs)
    result.append({"trade_date": data[window]["trade_date"],
                   "atr": round(atr_val, 4)})

    # Wilder 平滑
    for i in range(window, len(tr_list)):
        if tr_list[i] is not None:
            atr_val = (atr_val * (window - 1) + tr_list[i]) / window
            result.append({"trade_date": data[i + 1]["trade_date"],
                           "atr": round(atr_val, 4)})
        else:
            result.append({"trade_date": data[i + 1]["trade_date"], "atr": None})

    return result


def daily_obv(conn: sqlite3.Connection, symbol: str,
              period: int = 30) -> list[dict]:
    """OBV 能量潮。返回 [{trade_date, obv}, ...]。"""
    data = _fetch_daily_closes(conn, symbol, period)
    if len(data) < 2:
        return []

    result = [{"trade_date": data[0]["trade_date"],
               "obv": data[0]["volume"] or 0}]
    obv = data[0]["volume"] or 0
    for i in range(1, len(data)):
        if data[i]["close"] is None or data[i - 1]["close"] is None:
            result.append({"trade_date": data[i]["trade_date"], "obv": obv})
            continue
        vol = data[i]["volume"] or 0
        if data[i]["close"] > data[i - 1]["close"]:
            obv += vol
        elif data[i]["close"] < data[i - 1]["close"]:
            obv -= vol
        result.append({"trade_date": data[i]["trade_date"], "obv": obv})
    return result


def daily_kdj(conn: sqlite3.Connection, symbol: str,
              window: int = 9, period: int = 30) -> list[dict]:
    """KDJ 随机指标。返回 [{trade_date, k, d, j}, ...]。"""
    data = _fetch_daily_closes(conn, symbol, period)
    if len(data) < window:
        return []

    result = []
    prev_k, prev_d = 50.0, 50.0
    for i in range(len(data)):
        if i < window - 1:
            result.append({"trade_date": data[i]["trade_date"],
                           "k": None, "d": None, "j": None})
            continue
        window_data = data[i - window + 1:i + 1]
        highs = [d["high"] for d in window_data if d["high"] is not None]
        lows = [d["low"] for d in window_data if d["low"] is not None]
        if not highs or not lows:
            result.append({"trade_date": data[i]["trade_date"],
                           "k": None, "d": None, "j": None})
            continue
        hh, ll = max(highs), min(lows)
        c = data[i]["close"]
        if c is None or hh == ll:
            rsv = 50.0
        else:
            rsv = (c - ll) / (hh - ll) * 100
        k = 2 / 3 * prev_k + 1 / 3 * rsv
        d = 2 / 3 * prev_d + 1 / 3 * k
        j = 3 * k - 2 * d
        result.append({"trade_date": data[i]["trade_date"],
                       "k": round(k, 2), "d": round(d, 2), "j": round(j, 2)})
        prev_k, prev_d = k, d

    return result


# ============================================================================
# 一键计算：返回最新一行所有指标
# ============================================================================

def compute_latest(conn: sqlite3.Connection, symbol: str) -> dict:
    """计算最新一行的所有可用指标（盘中实时 + 离线历史）。

    返回 dict，指标不可用时值为 None。
    """
    result = {"symbol": symbol}

    # 盘中实时
    result["vwap"] = intraday_vwap(conn, symbol)
    result["volume_ratio"] = intraday_volume_ratio(conn, symbol)
    result["cumulative_volume"] = intraday_cumulative_volume(conn, symbol)

    spread = intraday_orderbook_spread(conn, symbol)
    result["bid_ask_spread"] = spread["spread"] if spread else None
    result["bid_ask_spread_pct"] = spread["spread_pct"] if spread else None

    imbalance = intraday_orderbook_imbalance(conn, symbol)
    result["orderbook_ratio"] = imbalance["ratio"] if imbalance else None

    # 离线历史（取最新值）
    def _latest(series, key):
        if not series:
            return None
        for item in reversed(series):
            if item.get(key) is not None:
                return item[key]
        return None

    ma5 = daily_ma(conn, symbol, 5)
    ma10 = daily_ma(conn, symbol, 10)
    ma20 = daily_ma(conn, symbol, 20)
    rsi14 = daily_rsi(conn, symbol, 14)
    macd_data = daily_macd(conn, symbol)
    boll20 = daily_boll(conn, symbol, 20)
    atr14 = daily_atr(conn, symbol, 14)
    kdj_data = daily_kdj(conn, symbol)

    result["ma5"] = _latest(ma5, "ma")
    result["ma10"] = _latest(ma10, "ma")
    result["ma20"] = _latest(ma20, "ma")
    result["rsi14"] = _latest(rsi14, "rsi")
    result["macd_dif"] = _latest(macd_data, "dif")
    result["macd_dea"] = _latest(macd_data, "dea")
    result["macd_bar"] = _latest(macd_data, "macd")
    result["boll_mid"] = _latest(boll20, "mid")
    result["boll_upper"] = _latest(boll20, "upper")
    result["boll_lower"] = _latest(boll20, "lower")
    result["atr14"] = _latest(atr14, "atr")
    result["kdj_k"] = _latest(kdj_data, "k")
    result["kdj_d"] = _latest(kdj_data, "d")
    result["kdj_j"] = _latest(kdj_data, "j")

    return result
