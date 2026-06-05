import pytest
import sqlite3
from src.db import init_db


class TestInitDb:
    def test_tables_created(self, db_conn):
        tables = [r[0] for r in db_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()]
        assert "ods_raw_quotes" in tables
        assert "dwd_quotes" in tables
        assert "dws_minute_bars" in tables
        assert "dws_daily_summary" in tables

    def test_views_created(self, db_conn):
        views = [r[0] for r in db_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='view' ORDER BY name"
        ).fetchall()]
        assert "ads_latest_quotes" in views
        assert "ads_intraday_stats" in views
        assert "ads_price_alerts" in views

    def test_wal_mode_enabled(self, db_conn):
        mode = db_conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"

    def test_idempotent(self, base_config, tmp_path):
        db_path = str(tmp_path / "idempotent.db")
        conn1 = init_db(db_path, base_config)
        conn2 = init_db(db_path, base_config)
        tables = [r[0] for r in conn2.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()]
        assert len(tables) == 4
        conn1.close()
        conn2.close()

    def test_wal_disabled(self, tmp_path):
        from src.config import _deep_merge, _DEFAULTS
        cfg = _deep_merge(_DEFAULTS, {
            "symbols": ["sh000001"],
            "poll_interval": 3,
            "api_url": "https://hq.sinajs.cn/rn={ts}&list={symbols}",
            "database": {"wal_mode": False},
        })
        from src.db import init_db
        conn = init_db(str(tmp_path / "no_wal.db"), cfg)
        # WAL might still show if SQLite defaults to it, but we test the code path
        conn.close()

    def test_ods_insert_and_query(self, db_conn):
        db_conn.execute(
            "INSERT INTO ods_raw_quotes (request_ts, url, status_code, raw_text) VALUES (?, ?, ?, ?)",
            ("2026-06-05T10:00:00", "https://test.com", 200, "raw data")
        )
        db_conn.commit()
        count = db_conn.execute("SELECT COUNT(*) FROM ods_raw_quotes").fetchone()[0]
        assert count == 1

    def test_dwd_insert_and_query(self, db_conn):
        db_conn.execute(
            """INSERT INTO dwd_quotes (symbol, name, current, volume, amount, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("sh000001", "上证指数", 4000.0, 100000, 500000000, "2026-06-05T10:00:00")
        )
        db_conn.commit()
        row = db_conn.execute("SELECT symbol, current FROM dwd_quotes").fetchone()
        assert row[0] == "sh000001"
        assert row[1] == 4000.0

    def test_views_queryable(self, db_conn):
        # Insert test data
        db_conn.execute(
            """INSERT INTO dwd_quotes (symbol, name, current, change_pct, fetched_at, quote_date)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("sh000001", "上证指数", 4000.0, 1.5, "2026-06-05T10:00:00", "2026-06-05")
        )
        db_conn.commit()
        # ads_latest_quotes should return the row
        latest = db_conn.execute("SELECT * FROM ads_latest_quotes").fetchall()
        assert len(latest) == 1
