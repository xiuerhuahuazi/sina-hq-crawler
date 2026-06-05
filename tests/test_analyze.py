import pytest
from datetime import datetime
from unittest.mock import patch
from src.db import init_db
from src.analyze import analyze_symbol, generate_report, get_db_path, main


def insert_dwd(conn, symbol, name, current, prev_close, volume, amount,
               quote_date=None, fetched_at=None, latency=25.0):
    if quote_date is None:
        quote_date = datetime.now().strftime('%Y-%m-%d')
    if fetched_at is None:
        fetched_at = datetime.now().isoformat()
    change_pct = (current / prev_close - 1) * 100 if prev_close else None
    conn.execute(
        """INSERT INTO dwd_quotes
           (symbol, name, current, prev_close, volume, amount, quote_date, fetched_at, latency_ms, change_pct, tick_index)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (symbol, name, current, prev_close, volume, amount, quote_date, fetched_at, latency, change_pct, 1)
    )
    conn.commit()


def insert_ods(conn, symbols_in, request_ts=None):
    if request_ts is None:
        request_ts = datetime.now().isoformat()
    conn.execute(
        "INSERT INTO ods_raw_quotes (request_ts, url, status_code, raw_text, symbols_in) VALUES (?, ?, ?, ?, ?)",
        (request_ts, "https://test.com", 200, "raw", symbols_in)
    )
    conn.commit()


class TestAnalyzeSymbol:
    def test_no_data_returns_none(self, db_conn_memory):
        result = analyze_symbol(db_conn_memory, "nonexistent")
        assert result is None

    def test_basic_stats(self, db_conn_memory):
        insert_dwd(db_conn_memory, "sh000001", "上证指数", 4000.0, 3900.0, 100000, 500000000)
        insert_ods(db_conn_memory, "sh000001")
        result = analyze_symbol(db_conn_memory, "sh000001")
        assert result is not None
        assert result['symbol'] == 'sh000001'
        assert result['name'] == '上证指数'
        assert result['tick_count'] == 1
        assert result['first_price'] == 4000.0
        assert result['last_price'] == 4000.0

    def test_date_filter(self, db_conn_memory):
        insert_dwd(db_conn_memory, "sh000001", "上证指数", 4000.0, 3900.0, 100000, 500000000,
                   quote_date="2026-06-01")
        insert_dwd(db_conn_memory, "sh000001", "上证指数", 4100.0, 3900.0, 200000, 600000000,
                   quote_date="2026-06-02")
        insert_ods(db_conn_memory, "sh000001")
        result = analyze_symbol(db_conn_memory, "sh000001", date="2026-06-01")
        assert result['tick_count'] == 1
        assert result['first_price'] == 4000.0

    def test_multiple_ticks(self, db_conn_memory):
        insert_dwd(db_conn_memory, "sh000001", "上证指数", 4000.0, 3900.0, 100000, 500000000,
                   fetched_at="2026-06-05T10:00:00")
        insert_dwd(db_conn_memory, "sh000001", "上证指数", 4010.0, 3900.0, 200000, 600000000,
                   fetched_at="2026-06-05T10:01:00")
        insert_ods(db_conn_memory, "sh000001")
        result = analyze_symbol(db_conn_memory, "sh000001")
        assert result['tick_count'] == 2
        assert result['min_price'] == 4000.0
        assert result['max_price'] == 4010.0

    def test_dedup_ratio(self, db_conn_memory):
        insert_dwd(db_conn_memory, "sh000001", "上证指数", 4000.0, 3900.0, 100000, 500000000)
        for _ in range(5):
            insert_ods(db_conn_memory, "sh000001")
        result = analyze_symbol(db_conn_memory, "sh000001")
        assert result['ods_count'] == 5
        assert result['dedup_ratio'] > 0


class TestGenerateReport:
    def test_basic_report(self, db_conn_memory, base_config, tmp_path):
        base_config['database']['path'] = str(tmp_path / "test.db")
        insert_dwd(db_conn_memory, "sh000001", "上证指数", 4000.0, 3900.0, 100000, 500000000)
        insert_ods(db_conn_memory, "sh000001")
        report = generate_report(db_conn_memory, base_config, symbols=["sh000001"])
        assert "上证指数" in report
        assert "sh000001" in report
        assert "数据概况" in report

    def test_no_data_symbol(self, db_conn_memory, base_config, tmp_path):
        base_config['database']['path'] = str(tmp_path / "test.db")
        report = generate_report(db_conn_memory, base_config, symbols=["nonexistent"])
        assert "无数据" in report

    def test_report_contains_health(self, db_conn_memory, base_config, tmp_path):
        base_config['database']['path'] = str(tmp_path / "test.db")
        insert_dwd(db_conn_memory, "sh000001", "上证指数", 4000.0, 3900.0, 100000, 500000000)
        insert_ods(db_conn_memory, "sh000001")
        report = generate_report(db_conn_memory, base_config, symbols=["sh000001"])
        assert "系统健康度" in report


class TestGetDbPath:
    def test_returns_path(self, base_config):
        assert get_db_path(base_config) == base_config['database']['path']


class TestMain:
    def test_missing_db_returns_1(self, tmp_path):
        cfg_file = tmp_path / "cfg.yaml"
        cfg_file.write_text("symbols:\n  - sh000001\ndatabase:\n  path: /nonexistent/db\n", encoding="utf-8")
        with patch('sys.argv', ['analyze', '--config', str(cfg_file)]):
            result = main()
        assert result == 1

    def test_output_to_file(self, tmp_path, base_config):
        db_path = str(tmp_path / "test.db")
        cfg_file = tmp_path / "cfg.yaml"
        cfg_file.write_text(f"symbols:\n  - sh000001\ndatabase:\n  path: {db_path}\n", encoding="utf-8")
        conn = init_db(db_path, base_config)
        insert_dwd(conn, "sh000001", "上证指数", 4000.0, 3900.0, 100000, 500000000)
        insert_ods(conn, "sh000001")
        conn.close()
        output_file = tmp_path / "report.md"
        with patch('sys.argv', ['analyze', '--config', str(cfg_file), '--output', str(output_file)]):
            result = main()
        assert result == 0
        assert output_file.exists()
        content = output_file.read_text(encoding='utf-8')
        assert "上证指数" in content

    def test_stdout_output(self, tmp_path, base_config, capsys):
        db_path = str(tmp_path / "test.db")
        cfg_file = tmp_path / "cfg.yaml"
        cfg_file.write_text(f"symbols:\n  - sh000001\ndatabase:\n  path: {db_path}\n", encoding="utf-8")
        conn = init_db(db_path, base_config)
        insert_dwd(conn, "sh000001", "上证指数", 4000.0, 3900.0, 100000, 500000000)
        insert_ods(conn, "sh000001")
        conn.close()
        with patch('sys.argv', ['analyze', '--config', str(cfg_file)]):
            result = main()
        assert result == 0
        captured = capsys.readouterr()
        assert "上证指数" in captured.out

    def test_symbol_override(self, tmp_path, base_config):
        db_path = str(tmp_path / "test.db")
        cfg_file = tmp_path / "cfg.yaml"
        cfg_file.write_text(f"symbols:\n  - sh000001\ndatabase:\n  path: {db_path}\n", encoding="utf-8")
        conn = init_db(db_path, base_config)
        insert_dwd(conn, "sh000001", "上证指数", 4000.0, 3900.0, 100000, 500000000)
        insert_ods(conn, "sh000001")
        conn.close()
        with patch('sys.argv', ['analyze', '--config', str(cfg_file), '--symbol', 'sh000001']):
            result = main()
        assert result == 0
