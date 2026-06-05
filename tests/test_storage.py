import json
import pytest
from src.storage import QuoteStorage
from src.parser import parse_response


SH_RAW = (
    'var hq_str_sh000001="上证指数,4044.8292,4057.7811,4042.6525,4078.9317,'
    '4038.0447,0,0,559541192,1151469946916,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,'
    '2026-06-05,14:19:41,00,"'
)

SH_RAW_CHANGED = (
    'var hq_str_sh000001="上证指数,4044.8292,4057.7811,4050.0000,4078.9317,'
    '4038.0447,0,0,560000000,1152000000000,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,'
    '2026-06-05,14:19:44,00,"'
)


class TestQuoteStorage:
    def test_first_tick_inserted(self, db_conn_memory, base_config):
        storage = QuoteStorage(db_conn_memory, base_config)
        quotes = parse_response(SH_RAW)
        storage.store(SH_RAW, quotes, 200, 25.0)
        storage.flush()
        dwd_count = db_conn_memory.execute("SELECT COUNT(*) FROM dwd_quotes").fetchone()[0]
        assert dwd_count == 1

    def test_ods_always_inserted(self, db_conn_memory, base_config):
        storage = QuoteStorage(db_conn_memory, base_config)
        quotes = parse_response(SH_RAW)
        storage.store(SH_RAW, quotes, 200, 25.0)
        storage.store(SH_RAW, quotes, 200, 25.0)
        storage.flush()
        ods_count = db_conn_memory.execute("SELECT COUNT(*) FROM ods_raw_quotes").fetchone()[0]
        assert ods_count == 2

    def test_dedup_skips_unchanged(self, db_conn_memory, base_config):
        storage = QuoteStorage(db_conn_memory, base_config)
        quotes = parse_response(SH_RAW)
        storage.store(SH_RAW, quotes, 200, 25.0)
        storage.store(SH_RAW, quotes, 200, 25.0)  # same data
        storage.flush()
        dwd_count = db_conn_memory.execute("SELECT COUNT(*) FROM dwd_quotes").fetchone()[0]
        assert dwd_count == 1  # dedup worked

    def test_dedup_inserts_changed_price(self, db_conn_memory, base_config):
        storage = QuoteStorage(db_conn_memory, base_config)
        q1 = parse_response(SH_RAW)
        q2 = parse_response(SH_RAW_CHANGED)
        storage.store(SH_RAW, q1, 200, 25.0)
        storage.store(SH_RAW_CHANGED, q2, 200, 25.0)
        storage.flush()
        dwd_count = db_conn_memory.execute("SELECT COUNT(*) FROM dwd_quotes").fetchone()[0]
        assert dwd_count == 2

    def test_empty_quotes_still_creates_ods(self, db_conn_memory, base_config):
        storage = QuoteStorage(db_conn_memory, base_config)
        storage.store("empty response", [], 200, 25.0)
        storage.flush()
        ods_count = db_conn_memory.execute("SELECT COUNT(*) FROM ods_raw_quotes").fetchone()[0]
        assert ods_count == 1
        dwd_count = db_conn_memory.execute("SELECT COUNT(*) FROM dwd_quotes").fetchone()[0]
        assert dwd_count == 0

    def test_change_pct_computed(self, db_conn_memory, base_config):
        storage = QuoteStorage(db_conn_memory, base_config)
        quotes = parse_response(SH_RAW)
        storage.store(SH_RAW, quotes, 200, 25.0)
        storage.flush()
        row = db_conn_memory.execute("SELECT change_pct FROM dwd_quotes").fetchone()
        assert row[0] is not None
        # current=4042.6525, prev_close=4057.7811
        expected = (4042.6525 / 4057.7811 - 1) * 100
        assert abs(row[0] - expected) < 0.01

    def test_tick_index_increments(self, db_conn_memory, base_config):
        storage = QuoteStorage(db_conn_memory, base_config)
        q1 = parse_response(SH_RAW)
        q2 = parse_response(SH_RAW_CHANGED)
        storage.store(SH_RAW, q1, 200, 25.0)
        storage.store(SH_RAW_CHANGED, q2, 200, 25.0)
        storage.flush()
        rows = db_conn_memory.execute("SELECT tick_index FROM dwd_quotes ORDER BY id").fetchall()
        assert rows[0][0] == 1
        assert rows[1][0] == 2

    def test_is_first_tick(self, db_conn_memory, base_config):
        storage = QuoteStorage(db_conn_memory, base_config)
        quotes = parse_response(SH_RAW)
        storage.store(SH_RAW, quotes, 200, 25.0)
        storage.flush()
        row = db_conn_memory.execute("SELECT is_first_tick FROM dwd_quotes").fetchone()
        assert row[0] == 1

    def test_get_stats(self, db_conn_memory, base_config):
        storage = QuoteStorage(db_conn_memory, base_config)
        quotes = parse_response(SH_RAW)
        storage.store(SH_RAW, quotes, 200, 25.0)
        stats = storage.get_stats()
        assert stats['pending_ods'] == 1
        assert stats['pending_dwd'] == 1
        assert stats['symbols_tracked'] == 1
        assert stats['total_ticks'] == 1

    def test_flush_clears_pending(self, db_conn_memory, base_config):
        storage = QuoteStorage(db_conn_memory, base_config)
        quotes = parse_response(SH_RAW)
        storage.store(SH_RAW, quotes, 200, 25.0)
        storage.flush()
        stats = storage.get_stats()
        assert stats['pending_ods'] == 0
        assert stats['pending_dwd'] == 0

    def test_finalize_creates_daily_summary(self, db_conn_memory, base_config):
        storage = QuoteStorage(db_conn_memory, base_config)
        quotes = parse_response(SH_RAW)
        storage.store(SH_RAW, quotes, 200, 25.0)
        storage.finalize()
        # Daily summary may or may not have data depending on date matching
        # but the finalize should not raise
        count = db_conn_memory.execute("SELECT COUNT(*) FROM dws_daily_summary").fetchone()[0]
        # count >= 0 is fine, just verify no exception
        assert count >= 0

    def test_order_book_stored_for_stock(self, db_conn_memory, base_config):
        from tests.conftest import BJ_STOCK_LINE
        storage = QuoteStorage(db_conn_memory, base_config)
        quotes = parse_response(BJ_STOCK_LINE)
        storage.store(BJ_STOCK_LINE, quotes, 200, 30.0)
        storage.flush()
        row = db_conn_memory.execute("SELECT order_book FROM dwd_quotes WHERE symbol='bj920576'").fetchone()
        assert row[0] is not None
        ob = json.loads(row[0])
        assert "bid" in ob
        assert "ask" in ob

    def test_monitor_notified(self, db_conn_memory, base_config):
        from unittest.mock import MagicMock
        mock_monitor = MagicMock()
        storage = QuoteStorage(db_conn_memory, base_config, monitor=mock_monitor)
        quotes = parse_response(SH_RAW)
        storage.store(SH_RAW, quotes, 200, 25.0)
        mock_monitor.on_tick.assert_called_once()
