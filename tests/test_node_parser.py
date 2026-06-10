"""Tests for src/node_parser.py — 节点数据解析器。"""

import pytest
from src.node_parser import parse_node_data, _safe_float


class TestSafeFloat:
    def test_valid_number(self):
        assert _safe_float("9.550") == 9.55

    def test_none(self):
        assert _safe_float(None) is None

    def test_empty_string(self):
        assert _safe_float("") is None

    def test_dash(self):
        assert _safe_float("-") is None

    def test_zero_returns_none(self):
        assert _safe_float(0) is None
        assert _safe_float("0") is None

    def test_invalid_string(self):
        assert _safe_float("abc") is None


class TestParseNodeData:
    def test_valid_items(self):
        items = [
            {
                "symbol": "sh600000", "code": "600000", "name": "浦发银行",
                "trade": "9.550", "pricechange": 0.18, "changepercent": 1.921,
                "buy": "9.540", "sell": "9.550", "settlement": "9.370",
                "open": "9.370", "high": "9.560", "low": "9.340",
                "volume": 52684975, "amount": 498861812, "ticktime": "10:58:59",
                "per": 6.283, "pb": 0.422,
                "mktcap": 31807075.5765, "nmc": 31807075.5765,
                "turnoverratio": 0.15819,
            }
        ]
        result = parse_node_data(items)
        assert len(result) == 1
        assert result[0]["symbol"] == "sh600000"
        assert result[0]["per"] == 6.283
        assert result[0]["pb"] == 0.422
        assert result[0]["mktcap"] > 0
        assert result[0]["turnoverratio"] == 0.15819

    def test_empty_symbol_skipped(self):
        items = [{"symbol": "", "name": "test"}]
        result = parse_node_data(items)
        assert len(result) == 0

    def test_empty_list(self):
        assert parse_node_data([]) == []

    def test_missing_fields(self):
        items = [{"symbol": "sh600000"}]
        result = parse_node_data(items)
        assert len(result) == 1
        assert result[0]["per"] is None
        assert result[0]["pb"] is None

    def test_dash_values(self):
        items = [{"symbol": "sh600000", "trade": "-", "per": "-", "pb": "-"}]
        result = parse_node_data(items)
        assert result[0]["trade"] is None
        assert result[0]["per"] is None
