#!/usr/bin/env python3
"""数据维护：过期清理、压缩归档"""

import argparse
import gzip
import json
import logging
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

from src.config import load_config

logger = logging.getLogger(__name__)

def archive_ods(conn, cutoff_ts: str, archive_dir: str) -> int:
    """Export expired ODS data to gzip-compressed JSONL file."""
    archive_path = Path(archive_dir)
    archive_path.mkdir(parents=True, exist_ok=True)

    # Get date range for filename
    row = conn.execute(
        "SELECT MIN(request_ts), MAX(request_ts) FROM ods_raw_quotes WHERE request_ts < ?",
        (cutoff_ts,)
    ).fetchone()

    if not row or not row[0]:
        return 0

    min_ts = row[0][:10].replace('-', '')
    max_ts = row[1][:10].replace('-', '')
    filename = f"ods_archive_{min_ts}_{max_ts}.jsonl.gz"
    filepath = archive_path / filename

    # Export rows
    rows = conn.execute(
        "SELECT id, request_ts, url, status_code, raw_text, latency_ms, parse_ok, error_detail, symbols_in FROM ods_raw_quotes WHERE request_ts < ?",
        (cutoff_ts,)
    ).fetchall()

    if not rows:
        return 0

    count = 0
    with gzip.open(filepath, 'wt', encoding='utf-8') as f:
        for row in rows:
            record = {
                'id': row[0], 'request_ts': row[1], 'url': row[2],
                'status_code': row[3], 'raw_text': row[4], 'latency_ms': row[5],
                'parse_ok': row[6], 'error_detail': row[7], 'symbols_in': row[8]
            }
            f.write(json.dumps(record, ensure_ascii=False) + '\n')
            count += 1

    logger.info("Archived %d ODS records to %s", count, filepath)
    return count

def run_retention_cleanup(conn, config: dict) -> dict:
    """Clean up expired data according to retention policy."""
    retention = config['retention']
    now = datetime.now()
    stats = {}

    # ODS cleanup (with optional archiving)
    cutoff_ods = (now - timedelta(days=retention['ods_days'])).isoformat()
    if retention.get('compress_on_cleanup'):
        archived = archive_ods(conn, cutoff_ods, retention['archive_dir'])
        stats['ods_archived'] = archived

    cursor = conn.execute("DELETE FROM ods_raw_quotes WHERE request_ts < ?", (cutoff_ods,))
    stats['ods_deleted'] = cursor.rowcount

    # DWD cleanup
    cutoff_dwd = (now - timedelta(days=retention['dwd_days'])).strftime('%Y-%m-%d')
    cursor = conn.execute("DELETE FROM dwd_quotes WHERE quote_date < ?", (cutoff_dwd,))
    stats['dwd_deleted'] = cursor.rowcount

    # DWS cleanup
    cutoff_dws = (now - timedelta(days=retention['dws_days'])).strftime('%Y-%m-%d')
    cursor = conn.execute("DELETE FROM dws_daily_summary WHERE trade_date < ?", (cutoff_dws,))
    stats['dws_summary_deleted'] = cursor.rowcount

    cursor = conn.execute("DELETE FROM dws_minute_bars WHERE bar_minute < ?", (cutoff_dws,))
    stats['dws_bars_deleted'] = cursor.rowcount

    conn.commit()

    # VACUUM to reclaim space
    db_size_before = conn.execute("PRAGMA page_count").fetchone()[0] * conn.execute("PRAGMA page_size").fetchone()[0]
    conn.execute("VACUUM")
    db_size_after = conn.execute("PRAGMA page_count").fetchone()[0] * conn.execute("PRAGMA page_size").fetchone()[0]
    stats['db_size_before_kb'] = db_size_before / 1024
    stats['db_size_after_kb'] = db_size_after / 1024
    stats['space_reclaimed_kb'] = (db_size_before - db_size_after) / 1024

    return stats

def print_cleanup_report(stats: dict):
    """Print cleanup summary."""
    print("\n=== 数据维护完成 ===")
    print(f"ODS 删除: {stats.get('ods_deleted', 0)} 条")
    if stats.get('ods_archived'):
        print(f"ODS 归档: {stats['ods_archived']} 条")
    print(f"DWD 删除: {stats.get('dwd_deleted', 0)} 条")
    print(f"DWS 日终汇总删除: {stats.get('dws_summary_deleted', 0)} 条")
    print(f"DWS 分钟K线删除: {stats.get('dws_bars_deleted', 0)} 条")
    print(f"数据库大小: {stats.get('db_size_before_kb', 0):.1f} KB → {stats.get('db_size_after_kb', 0):.1f} KB")
    print(f"回收空间: {stats.get('space_reclaimed_kb', 0):.1f} KB")

def main():
    parser = argparse.ArgumentParser(description="数据维护工具")
    parser.add_argument('--config', '-c', default=None, help='配置文件路径')
    parser.add_argument('--dry-run', action='store_true', help='只显示将删除的数据量，不实际删除')
    args = parser.parse_args()

    config = load_config(args.config)
    db_path = config['database']['path']

    if not Path(db_path).exists():
        print(f"数据库不存在: {db_path}")
        return 1

    conn = sqlite3.connect(db_path)

    if args.dry_run:
        now = datetime.now()
        retention = config['retention']

        cutoff_ods = (now - timedelta(days=retention['ods_days'])).isoformat()
        cutoff_dwd = (now - timedelta(days=retention['dwd_days'])).strftime('%Y-%m-%d')
        cutoff_dws = (now - timedelta(days=retention['dws_days'])).strftime('%Y-%m-%d')

        ods = conn.execute("SELECT COUNT(*) FROM ods_raw_quotes WHERE request_ts < ?", (cutoff_ods,)).fetchone()[0]
        dwd = conn.execute("SELECT COUNT(*) FROM dwd_quotes WHERE quote_date < ?", (cutoff_dwd,)).fetchone()[0]
        dws_s = conn.execute("SELECT COUNT(*) FROM dws_daily_summary WHERE trade_date < ?", (cutoff_dws,)).fetchone()[0]
        dws_b = conn.execute("SELECT COUNT(*) FROM dws_minute_bars WHERE bar_minute < ?", (cutoff_dws,)).fetchone()[0]

        print("=== Dry Run: 预计清理 ===")
        print(f"ODS (>{retention['ods_days']}天): {ods} 条")
        print(f"DWD (>{retention['dwd_days']}天): {dwd} 条")
        print(f"DWS 日终汇总 (>{retention['dws_days']}天): {dws_s} 条")
        print(f"DWS 分钟K线 (>{retention['dws_days']}天): {dws_b} 条")
    else:
        stats = run_retention_cleanup(conn, config)
        print_cleanup_report(stats)

    conn.close()
    return 0

if __name__ == "__main__":
    sys.exit(main() or 0)
