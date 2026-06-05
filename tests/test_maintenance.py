import gzip
import json
import pytest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from src.db import init_db
from src.maintenance import archive_ods, run_retention_cleanup, print_cleanup_report, main


def insert_old_ods(conn, days_ago=10):
    ts = (datetime.now() - timedelta(days=days_ago)).isoformat()
    conn.execute(
        "INSERT INTO ods_raw_quotes (request_ts, url, status_code, raw_text) VALUES (?, ?, ?, ?)",
        (ts, "https://test.com", 200, "old data")
    )
    conn.commit()


def insert_old_dwd(conn, days_ago=100):
    date = (datetime.now() - timedelta(days=days_ago)).strftime('%Y-%m-%d')
    conn.execute(
        "INSERT INTO dwd_quotes (symbol, name, quote_date, current, fetched_at) VALUES (?, ?, ?, ?, ?)",
        ("sh000001", "上证指数", date, 4000.0, f"{date}T10:00:00")
    )
    conn.commit()


class TestArchiveOds:
    def test_no_rows_returns_zero(self, db_conn_memory):
        count = archive_ods(db_conn_memory, "2099-01-01T00:00:00", "/tmp/test_archive")
        assert count == 0

    def test_archives_old_rows(self, db_conn_memory, tmp_path):
        insert_old_ods(db_conn_memory, 10)
        archive_dir = str(tmp_path / "archives")
        count = archive_ods(
            db_conn_memory,
            (datetime.now() - timedelta(days=5)).isoformat(),
            archive_dir
        )
        assert count == 1
        # Verify archive file exists and is valid gzip JSONL
        archive_files = list(Path(archive_dir).glob("ods_archive_*.jsonl.gz"))
        assert len(archive_files) == 1
        with gzip.open(archive_files[0], 'rt', encoding='utf-8') as f:
            records = [json.loads(line) for line in f]
        assert len(records) == 1
        assert records[0]['url'] == "https://test.com"


class TestRunRetentionCleanup:
    def test_cleans_old_data(self, db_conn_memory, base_config, tmp_path):
        base_config['retention']['archive_dir'] = str(tmp_path / "archives")
        insert_old_ods(db_conn_memory, 10)
        insert_old_dwd(db_conn_memory, 100)
        stats = run_retention_cleanup(db_conn_memory, base_config)
        assert stats['ods_deleted'] == 1
        assert stats['dwd_deleted'] == 1

    def test_preserves_recent_data(self, db_conn_memory, base_config, tmp_path):
        base_config['retention']['archive_dir'] = str(tmp_path / "archives")
        # Insert recent data
        conn = db_conn_memory
        conn.execute(
            "INSERT INTO ods_raw_quotes (request_ts, url, status_code, raw_text) VALUES (?, ?, ?, ?)",
            (datetime.now().isoformat(), "https://test.com", 200, "recent")
        )
        conn.execute(
            "INSERT INTO dwd_quotes (symbol, name, quote_date, current, fetched_at) VALUES (?, ?, ?, ?, ?)",
            ("sh000001", "上证指数", datetime.now().strftime('%Y-%m-%d'), 4000.0, datetime.now().isoformat())
        )
        conn.commit()
        stats = run_retention_cleanup(conn, base_config)
        assert stats['ods_deleted'] == 0
        assert stats['dwd_deleted'] == 0

    def test_compress_disabled(self, db_conn_memory, base_config, tmp_path):
        base_config['retention']['compress_on_cleanup'] = False
        base_config['retention']['archive_dir'] = str(tmp_path / "archives")
        insert_old_ods(db_conn_memory, 10)
        stats = run_retention_cleanup(db_conn_memory, base_config)
        assert 'ods_archived' not in stats
        assert stats['ods_deleted'] == 1


class TestPrintCleanupReport:
    def test_prints_without_error(self, capsys):
        print_cleanup_report({
            'ods_deleted': 5, 'dwd_deleted': 10,
            'ods_archived': 5, 'dws_summary_deleted': 2,
            'dws_bars_deleted': 3,
            'db_size_before_kb': 100.0, 'db_size_after_kb': 80.0,
            'space_reclaimed_kb': 20.0,
        })
        captured = capsys.readouterr()
        assert "5" in captured.out
        assert "10" in captured.out


class TestMain:
    def test_dry_run(self, tmp_path, base_config):
        db_path = str(tmp_path / "test.db")
        cfg_file = tmp_path / "cfg.yaml"
        cfg_file.write_text(f"symbols:\n  - sh000001\ndatabase:\n  path: {db_path}\n", encoding="utf-8")
        conn = init_db(db_path, base_config)
        insert_old_ods(conn, 10)
        conn.close()
        with patch('sys.argv', ['maintain', '--config', str(cfg_file), '--dry-run']):
            result = main()
        assert result == 0

    def test_normal_run(self, tmp_path, base_config):
        db_path = str(tmp_path / "test.db")
        cfg_file = tmp_path / "cfg.yaml"
        cfg_file.write_text(
            f"symbols:\n  - sh000001\ndatabase:\n  path: {db_path}\nretention:\n  archive_dir: {tmp_path}/archives/\n",
            encoding="utf-8"
        )
        conn = init_db(db_path, base_config)
        insert_old_ods(conn, 10)
        conn.close()
        with patch('sys.argv', ['maintain', '--config', str(cfg_file)]):
            result = main()
        assert result == 0

    def test_missing_db(self, tmp_path):
        cfg_file = tmp_path / "cfg.yaml"
        cfg_file.write_text(f"symbols:\n  - sh000001\ndatabase:\n  path: /nonexistent/db\n", encoding="utf-8")
        with patch('sys.argv', ['maintain', '--config', str(cfg_file)]):
            result = main()
        assert result == 1
