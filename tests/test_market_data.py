"""Tests for src/market_data.py — 市场数据加载器。"""

import json
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime

from src.db import init_db
from src.market_data import MarketDataLoader


@pytest.fixture
def conn(base_config, tmp_path):
    c = init_db(str(tmp_path / "test.db"), base_config)
    yield c
    c.close()


class TestStoreNodeData:
    def test_stores_data(self, conn, base_config):
        """正常存储节点数据。"""
        loader = MarketDataLoader(conn, base_config)
        items = [{
            "symbol": "sh600000", "code": "600000", "name": "浦发银行",
            "trade": 9.55, "pricechange": 0.18, "changepercent": 1.921,
            "buy": 9.54, "sell": 9.55, "settlement": 9.37,
            "open": 9.37, "high": 9.56, "low": 9.34,
            "volume": 52684975, "amount": 498861812, "ticktime": "10:58:59",
            "per": 6.283, "pb": 0.422,
            "mktcap": 31807075.5765, "nmc": 31807075.5765,
            "turnoverratio": 0.15819,
        }]
        loader._store_node_data(items)

        row = conn.execute(
            "SELECT symbol, per, pb, mktcap, nmc, turnoverratio FROM dwd_node_data WHERE symbol = ?",
            ("sh600000",)
        ).fetchone()
        assert row is not None
        assert row[0] == "sh600000"
        assert row[1] == 6.283  # per
        assert row[2] == 0.422  # pb
        assert row[3] > 0       # mktcap
        assert row[5] > 0       # turnoverratio

    def test_upsert_updates(self, conn, base_config):
        """重复 symbol 被更新而非重复插入。"""
        loader = MarketDataLoader(conn, base_config)
        items = [{
            "symbol": "sh600000", "code": "600000", "name": "浦发银行",
            "trade": 9.55, "pricechange": 0.18, "changepercent": 1.921,
            "buy": 9.54, "sell": 9.55, "settlement": 9.37,
            "open": 9.37, "high": 9.56, "low": 9.34,
            "volume": 52684975, "amount": 498861812, "ticktime": "10:58:59",
            "per": 6.283, "pb": 0.422, "mktcap": 31807075, "nmc": 31807075,
            "turnoverratio": 0.15819,
        }]
        loader._store_node_data(items)
        items[0]["per"] = 7.0
        loader._store_node_data(items)

        row = conn.execute(
            "SELECT per FROM dwd_node_data WHERE symbol = ?",
            ("sh600000",)
        ).fetchone()
        assert row[0] == 7.0

        count = conn.execute("SELECT COUNT(*) FROM dwd_node_data").fetchone()[0]
        assert count == 1


class TestSymbolFundamentalsView:
    def test_view_works(self, conn, base_config):
        """ads_symbol_fundamentals 视图正常工作。"""
        loader = MarketDataLoader(conn, base_config)
        items = [{
            "symbol": "sh600000", "code": "600000", "name": "浦发银行",
            "trade": 9.55, "pricechange": 0.18, "changepercent": 1.921,
            "buy": 9.54, "sell": 9.55, "settlement": 9.37,
            "open": 9.37, "high": 9.56, "low": 9.34,
            "volume": 52684975, "amount": 498861812, "ticktime": "10:58:59",
            "per": 6.283, "pb": 0.422, "mktcap": 31807075, "nmc": 31807075,
            "turnoverratio": 0.15819,
        }]
        loader._store_node_data(items)

        # 插入行业分类
        conn.execute("""
            INSERT INTO dim_symbol_classifications
            (symbol, classification_type, classification_code, updated_at)
            VALUES (?, 'sw_industry', 'sw_yyhy', ?)
        """, ("sh600000", datetime.now().isoformat()))
        conn.commit()

        row = conn.execute(
            "SELECT symbol, per, pb, sw_industry FROM ads_symbol_fundamentals WHERE symbol = ?",
            ("sh600000",)
        ).fetchone()
        assert row is not None
        assert row[1] == 6.283
        assert row[3] == "sw_yyhy"


class TestLoadNodeData:
    @patch.object(MarketDataLoader, '_store_node_data')
    def test_calls_fetcher(self, mock_store, conn, base_config):
        """load_node_data 调用 fetcher 和 store。"""
        loader = MarketDataLoader(conn, base_config)
        with patch.object(loader._fetcher, 'fetch_all', return_value=[
            {"symbol": "sh600000", "code": "600000", "name": "浦发银行",
             "trade": "9.55", "per": 6.283, "pb": 0.422}
        ]):
            count = loader.load_node_data(["hs_a"])
        assert count == 1

    def test_empty_nodes(self, conn, base_config):
        """空节点列表返回 0。"""
        loader = MarketDataLoader(conn, base_config)
        count = loader.load_node_data([])
        assert count == 0
