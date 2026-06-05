import json
import pytest
from src.parser import _float, parse_quote, parse_response


class TestFloat:
    def test_valid_number(self):
        assert _float("4044.8292") == 4044.8292

    def test_zero_returns_none(self):
        assert _float("0") is None
        assert _float("0.0") is None

    def test_empty_string(self):
        assert _float("") is None

    def test_none_input(self):
        assert _float(None) is None

    def test_non_numeric(self):
        assert _float("abc") is None

    def test_negative_number(self):
        assert _float("-3.14") == -3.14

    def test_integer_string(self):
        assert _float("100") == 100.0


class TestParseQuote:
    def test_valid_index(self, sh_index_line):
        q = parse_quote(sh_index_line)
        assert q is not None
        assert q["symbol"] == "sh000001"
        assert q["name"] == "上证指数"
        assert q["current"] == 4042.6525
        assert q["open"] == 4044.8292
        assert q["prev_close"] == 4057.7811
        assert q["high"] == 4078.9317
        assert q["low"] == 4038.0447
        assert q["volume"] == 559541192.0
        assert q["quote_date"] == "2026-06-05"
        assert q["quote_time"] == "14:19:41"
        assert q["order_book"] is None  # index has no order book

    def test_valid_stock_with_order_book(self, bj_stock_line):
        q = parse_quote(bj_stock_line)
        assert q is not None
        assert q["symbol"] == "bj920576"
        assert q["name"] == "天力复合"
        assert q["current"] == 69.690
        assert q["order_book"] is not None
        ob = json.loads(q["order_book"])
        assert "bid" in ob
        assert "ask" in ob
        assert len(ob["bid"]) > 0
        assert len(ob["ask"]) > 0
        assert ob["bid"][0]["p"] == 69.600

    def test_invalid_line_returns_none(self):
        assert parse_quote("not a valid line") is None

    def test_too_few_fields(self):
        line = 'var hq_str_sh000001="field1,field2,field3"'
        assert parse_quote(line) is None

    def test_empty_line(self):
        assert parse_quote("") is None

    def test_whitespace_stripped(self, sh_index_line):
        q = parse_quote("  " + sh_index_line + "  ")
        assert q is not None
        assert q["symbol"] == "sh000001"

    def test_sz_index_no_order_book(self):
        line = (
            'var hq_str_sz399001="深证成指,15595.695,15661.574,15393.238,15710.144,'
            '15391.859,0.000,0.000,70047317763,1443951070526.790,'
            '0,0.000,0,0.000,0,0.000,0,0.000,0,0.000,0,0.000,0,0.000,0,0.000,0,0.000,0,0.000,'
            '2026-06-05,14:19:03,00"'
        )
        q = parse_quote(line)
        assert q is not None
        assert q["symbol"] == "sz399001"
        assert q["order_book"] is None


class TestParseResponse:
    def test_empty_string(self):
        assert parse_response("") == []

    def test_multiple_lines(self, sh_index_line, bj_stock_line):
        text = sh_index_line + "\n" + bj_stock_line
        quotes = parse_response(text)
        assert len(quotes) == 2
        assert quotes[0]["symbol"] == "sh000001"
        assert quotes[1]["symbol"] == "bj920576"

    def test_invalid_lines_skipped(self, sh_index_line):
        text = "invalid line\n" + sh_index_line + "\nalso invalid"
        quotes = parse_response(text)
        assert len(quotes) == 1

    def test_empty_lines_skipped(self, sh_index_line):
        text = "\n\n" + sh_index_line + "\n\n"
        quotes = parse_response(text)
        assert len(quotes) == 1
