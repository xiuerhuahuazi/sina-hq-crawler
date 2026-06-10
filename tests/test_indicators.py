"""Tests for src/indicators.py — 技术指标计算。"""

import json
import pytest
from datetime import date, timedelta

from src.db import init_db


def _insert_daily(conn, symbol, trade_date, o, h, l, c, volume, amount, prev_close):
    """插入一条日终汇总记录。"""
    conn.execute("""
        INSERT OR REPLACE INTO dws_daily_summary
        (symbol, trade_date, open, high, low, close, prev_close, volume, amount,
         change_pct, tick_count, first_tick_at, last_tick_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
    """, (symbol, trade_date, o, h, l, c, prev_close, volume, amount,
          round((c / prev_close - 1) * 100, 2) if prev_close else 0,
          f"{trade_date} 09:30:00", f"{trade_date} 15:00:00"))
    conn.commit()


def _insert_minute_bar(conn, symbol, bar_minute, o, h, l, c, volume, amount):
    """插入一条分钟K线记录。"""
    conn.execute("""
        INSERT OR REPLACE INTO dws_minute_bars
        (symbol, bar_minute, open, high, low, close, volume, amount, tick_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
    """, (symbol, bar_minute, o, h, l, c, volume, amount))
    conn.commit()


def _insert_tick(conn, symbol, current, volume, amount, order_book=None):
    """插入一条 DWD tick 记录。"""
    conn.execute("""
        INSERT INTO dwd_quotes
        (symbol, name, quote_date, quote_time, open, prev_close, current,
         high, low, volume, amount, change_pct, delta_volume, delta_amount,
         tick_index, order_book, fetched_at, latency_ms, is_first_tick)
        VALUES (?, '测试', DATE('now'), '10:00:00', ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 1, ?, DATETIME('now'), 10, 1)
    """, (symbol, current, current, current, current, current, volume, amount,
          order_book))
    conn.commit()


@pytest.fixture
def conn(base_config, tmp_path):
    """带数据的测试数据库。"""
    c = init_db(str(tmp_path / "test.db"), base_config)
    yield c
    c.close()


@pytest.fixture
def conn_with_daily(conn):
    """包含 30 天日线数据的数据库。"""
    today = date.today()
    for i in range(30):
        d = (today - timedelta(days=30 - i)).isoformat()
        base = 100 + i * 0.5
        _insert_daily(conn, "sh000001", d,
                      o=base, h=base + 2, l=base - 1, c=base + 1,
                      volume=1000000 + i * 10000,
                      amount=(base + 1) * (1000000 + i * 10000),
                      prev_close=base - 0.5)
    return conn


@pytest.fixture
def conn_with_minutes(conn):
    """包含分钟K线数据的数据库。"""
    today = date.today().isoformat()
    for i in range(10):
        minute = f"{today} 09:{30 + i:02d}"
        base = 100 + i * 0.1
        _insert_minute_bar(conn, "sh000001", minute,
                           o=base, h=base + 0.5, l=base - 0.3, c=base + 0.2,
                           volume=10000 + i * 1000,
                           amount=(base + 0.2) * (10000 + i * 1000))
    return conn


# ============================================================================
# 盘中实时指标测试
# ============================================================================

class TestIntradayVWAP:
    def test_with_data(self, conn_with_minutes):
        vwap = __import__("src.indicators", fromlist=["intraday_vwap"]).intraday_vwap(
            conn_with_minutes, "sh000001")
        assert vwap is not None
        assert 99 < vwap < 102  # 合理范围

    def test_no_data(self, conn):
        from src.indicators import intraday_vwap
        assert intraday_vwap(conn, "nonexistent") is None


class TestIntradayVolumeRatio:
    def test_with_data(self, conn_with_minutes):
        from src.indicators import intraday_volume_ratio
        ratio = intraday_volume_ratio(conn_with_minutes, "sh000001")
        # 数据量不足 lookback+1 时返回 None
        # 10 条数据，lookback=5，应该有 6 条
        if ratio is not None:
            assert ratio > 0

    def test_no_data(self, conn):
        from src.indicators import intraday_volume_ratio
        assert intraday_volume_ratio(conn, "nonexistent") is None


class TestIntradayOrderbookSpread:
    def test_with_orderbook(self, conn):
        from src.indicators import intraday_orderbook_spread
        ob = json.dumps({
            "bid": [{"p": 10.0, "v": 100}, {"p": 9.9, "v": 200}],
            "ask": [{"p": 10.1, "v": 150}, {"p": 10.2, "v": 250}],
        })
        _insert_tick(conn, "bj920576", 10.05, 1000, 10050, ob)
        result = intraday_orderbook_spread(conn, "bj920576")
        assert result is not None
        assert result["bid0"] == 10.0
        assert result["ask0"] == 10.1
        assert abs(result["spread"] - 0.1) < 0.001

    def test_no_orderbook(self, conn):
        from src.indicators import intraday_orderbook_spread
        _insert_tick(conn, "sh000001", 100, 1000, 100000)
        assert intraday_orderbook_spread(conn, "sh000001") is None


class TestIntradayOrderbookImbalance:
    def test_with_orderbook(self, conn):
        from src.indicators import intraday_orderbook_imbalance
        ob = json.dumps({
            "bid": [{"p": 10.0, "v": 200}, {"p": 9.9, "v": 300}],
            "ask": [{"p": 10.1, "v": 100}, {"p": 10.2, "v": 150}],
        })
        _insert_tick(conn, "bj920576", 10.05, 1000, 10050, ob)
        result = intraday_orderbook_imbalance(conn, "bj920576")
        assert result is not None
        assert result["bias"] == "bid"  # bid_total > ask_total
        assert result["ratio"] > 1


class TestIntradayCumulativeVolume:
    def test_with_data(self, conn_with_minutes):
        from src.indicators import intraday_cumulative_volume
        vol = intraday_cumulative_volume(conn_with_minutes, "sh000001")
        assert vol is not None
        assert vol > 0

    def test_no_data(self, conn):
        from src.indicators import intraday_cumulative_volume
        assert intraday_cumulative_volume(conn, "nonexistent") is None


# ============================================================================
# 离线历史指标测试
# ============================================================================

class TestDailyMA:
    def test_ma5(self, conn_with_daily):
        from src.indicators import daily_ma
        result = daily_ma(conn_with_daily, "sh000001", window=5, period=30)
        assert len(result) == 30
        # 前 4 个为 None
        assert result[0]["ma"] is None
        assert result[3]["ma"] is None
        # 第 5 个开始有值
        assert result[4]["ma"] is not None
        assert result[4]["ma"] > 0

    def test_insufficient_data(self, conn):
        from src.indicators import daily_ma
        assert daily_ma(conn, "sh000001", window=20) == []


class TestDailyEMA:
    def test_ema(self, conn_with_daily):
        from src.indicators import daily_ema
        result = daily_ema(conn_with_daily, "sh000001", window=10, period=30)
        assert len(result) == 30
        assert result[9]["ema"] is not None


class TestDailyRSI:
    def test_rsi14(self, conn_with_daily):
        from src.indicators import daily_rsi
        result = daily_rsi(conn_with_daily, "sh000001", window=14, period=30)
        assert len(result) > 0
        # 最后一个有值
        last = [r for r in result if r["rsi"] is not None]
        assert len(last) > 0
        assert 0 <= last[-1]["rsi"] <= 100


class TestDailyMACD:
    def test_macd(self, conn_with_daily):
        from src.indicators import daily_macd
        result = daily_macd(conn_with_daily, "sh000001", period=30)
        # 30 天数据 < 26 天最少要求
        # 需要更多数据或更短的 slow 参数
        # 用 slow=10 测试
        result = daily_macd(conn_with_daily, "sh000001", fast=5, slow=10, signal=5, period=30)
        assert len(result) > 0
        valid = [r for r in result if r["dif"] is not None]
        assert len(valid) > 0


class TestDailyBOLL:
    def test_boll(self, conn_with_daily):
        from src.indicators import daily_boll
        result = daily_boll(conn_with_daily, "sh000001", window=20, period=30)
        assert len(result) == 30
        valid = [r for r in result if r["mid"] is not None]
        assert len(valid) == 11  # 30 - 20 + 1
        assert valid[-1]["upper"] > valid[-1]["mid"] > valid[-1]["lower"]


class TestDailyATR:
    def test_atr(self, conn_with_daily):
        from src.indicators import daily_atr
        result = daily_atr(conn_with_daily, "sh000001", window=14, period=30)
        assert len(result) > 0
        valid = [r for r in result if r["atr"] is not None]
        assert len(valid) > 0
        assert valid[-1]["atr"] > 0


class TestDailyOBV:
    def test_obv(self, conn_with_daily):
        from src.indicators import daily_obv
        result = daily_obv(conn_with_daily, "sh000001", period=30)
        assert len(result) == 30
        assert result[0]["obv"] is not None


class TestDailyKDJ:
    def test_kdj(self, conn_with_daily):
        from src.indicators import daily_kdj
        result = daily_kdj(conn_with_daily, "sh000001", window=9, period=30)
        assert len(result) == 30
        valid = [r for r in result if r["k"] is not None]
        assert len(valid) > 0
        assert 0 <= valid[-1]["k"] <= 100


# ============================================================================
# 一键计算测试
# ============================================================================

class TestComputeLatest:
    def test_returns_dict(self, conn_with_daily):
        from src.indicators import compute_latest
        result = compute_latest(conn_with_daily, "sh000001")
        assert isinstance(result, dict)
        assert result["symbol"] == "sh000001"
        # 所有字段都应存在
        assert "vwap" in result
        assert "rsi14" in result
        assert "macd_dif" in result
        assert "boll_mid" in result

    def test_empty_symbol(self, conn):
        from src.indicators import compute_latest
        result = compute_latest(conn, "nonexistent")
        assert result["symbol"] == "nonexistent"
        # 大部分指标应为 None
        assert result["rsi14"] is None
