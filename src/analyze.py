#!/usr/bin/env python3
"""行情数据分析与报告生成"""

import argparse
import sqlite3
import sys
import logging
from datetime import datetime
from pathlib import Path

from src.config import load_config

logger = logging.getLogger(__name__)

def get_db_path(config):
    return config['database']['path']

def analyze_symbol(conn, symbol: str, date: str = None) -> dict:
    """Analyze a single symbol using SQL aggregation."""
    date_filter = ""
    params = [symbol]
    if date:
        date_filter = "AND quote_date = ?"
        params.append(date)

    # Basic stats
    row = conn.execute(f"""
        SELECT COUNT(*), MIN(current), MAX(current), AVG(current),
               MIN(fetched_at), MAX(fetched_at),
               MIN(latency_ms), MAX(latency_ms), AVG(latency_ms)
        FROM dwd_quotes
        WHERE symbol = ? {date_filter}
    """, params).fetchone()

    if not row or row[0] == 0:
        return None

    count, min_price, max_price, avg_price, first_at, last_at, min_lat, max_lat, avg_lat = row

    # First and last price
    first_row = conn.execute(f"""
        SELECT current, prev_close, name FROM dwd_quotes
        WHERE symbol = ? {date_filter} ORDER BY fetched_at LIMIT 1
    """, params).fetchone()

    last_row = conn.execute(f"""
        SELECT current, volume, amount FROM dwd_quotes
        WHERE symbol = ? {date_filter} ORDER BY fetched_at DESC LIMIT 1
    """, params).fetchone()

    # Dedup stats: count how many ODS rounds contain this symbol
    # Each ODS record may contain multiple symbols, so we count records
    # where this symbol appears, but normalize by the average symbols per request
    ods_total = conn.execute("SELECT COUNT(*) FROM ods_raw_quotes").fetchone()[0]
    # Approximate: assume each ODS request covers the same number of symbols
    # For per-symbol ratio, use DWD tick count vs expected (ods_total) directly
    ods_count = ods_total  # each round fetches all symbols together

    # Latency percentiles (approximate via ordered selection)
    latencies = conn.execute(f"""
        SELECT latency_ms FROM dwd_quotes
        WHERE symbol = ? {date_filter} AND latency_ms IS NOT NULL
        ORDER BY latency_ms
    """, params).fetchall()

    lat_list = [r[0] for r in latencies]
    p50 = lat_list[len(lat_list)//2] if lat_list else 0
    p95 = lat_list[int(len(lat_list)*0.95)] if lat_list else 0

    # Gap detection (consecutive identical prices)
    prices = conn.execute(f"""
        SELECT current FROM dwd_quotes
        WHERE symbol = ? {date_filter} ORDER BY fetched_at
    """, params).fetchall()

    price_list = [r[0] for r in prices if r[0] is not None]
    dup_count = sum(1 for i in range(1, len(price_list)) if price_list[i] == price_list[i-1])

    return {
        'symbol': symbol,
        'name': first_row[2] if first_row else symbol,
        'tick_count': count,
        'ods_count': ods_count,
        'dedup_ratio': (1 - count / ods_count) * 100 if ods_count > 0 else 0,
        'first_price': first_row[0] if first_row else None,
        'last_price': last_row[0] if last_row else None,
        'prev_close': first_row[1] if first_row else None,
        'min_price': min_price,
        'max_price': max_price,
        'avg_price': avg_price,
        'price_range': max_price - min_price if min_price and max_price else 0,
        'price_range_pct': (max_price - min_price) / min_price * 100 if min_price and min_price > 0 else 0,
        'dup_count': dup_count,
        'dup_pct': dup_count / (count - 1) * 100 if count > 1 else 0,
        'first_at': first_at,
        'last_at': last_at,
        'volume': last_row[1] if last_row else 0,
        'amount': last_row[2] if last_row else 0,
        'avg_latency': avg_lat or 0,
        'p50_latency': p50,
        'p95_latency': p95,
        'max_latency': max_lat or 0,
        'latency_gt_500': sum(1 for lat in lat_list if lat > 500),
        'latency_gt_1000': sum(1 for lat in lat_list if lat > 1000),
    }

def generate_report(conn, config, date: str = None, symbols: list = None) -> str:
    """Generate markdown analysis report."""
    if symbols is None:
        symbols = config['symbols']

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db_path = Path(config['database']['path'])
    db_size = db_path.stat().st_size / 1024 if db_path.exists() else 0

    # DWD total count
    dwd_count = conn.execute("SELECT COUNT(*) FROM dwd_quotes").fetchone()[0]
    ods_count = conn.execute("SELECT COUNT(*) FROM ods_raw_quotes").fetchone()[0]

    # Overall dedup: compare DWD count against expected (ODS rounds × symbols)
    expected_ticks = ods_count * len(symbols)
    overall_dedup = (1 - dwd_count / expected_ticks) * 100 if expected_ticks > 0 else 0

    report = f"""# 新浪行情采集系统 — 数据分析报告

> 生成时间: {now}
> 数据库: {db_path.name} ({db_size:.1f} KB)
> 分析日期: {date or '全部'}

## 数据概况

| 指标 | 值 |
|------|-----|
| ODS 采集轮次 | {ods_count} |
| DWD 清洗记录 | {dwd_count} |
| 预期总 tick 数 | {expected_ticks} |
| 整体去重率 | {overall_dedup:.1f}% |
| 分析标的数 | {len(symbols)} |

"""

    for symbol in symbols:
        stats = analyze_symbol(conn, symbol, date)
        if not stats:
            report += f"### {symbol}\n\n无数据\n\n"
            continue

        # Change percentage
        change_pct = 0
        if stats['prev_close'] and stats['last_price'] and stats['prev_close'] != 0:
            change_pct = (stats['last_price'] / stats['prev_close'] - 1) * 100
        sign = "+" if change_pct >= 0 else ""

        report += f"""### {stats['name']} (`{symbol}`)

**价格表现**

| 指标 | 值 |
|------|-----|
| 起始价 | {stats['first_price']:.4f} |
| 结束价 | {stats['last_price']:.4f} |
| 涨跌幅 | {sign}{change_pct:.2f}% |
| 最高价 | {stats['max_price']:.4f} |
| 最低价 | {stats['min_price']:.4f} |
| 波动幅度 | {stats['price_range']:.4f} ({stats['price_range_pct']:.4f}%) |
| 连续相同价格 | {stats['dup_count']} ({stats['dup_pct']:.1f}%) |

**成交量/额**

| 指标 | 值 |
|------|-----|
| 成交量 | {stats['volume']:,.0f} |
| 成交额 | {stats['amount']:,.2f} 元 ({stats['amount']/1e8:.2f} 亿) |

**数据质量**

| 指标 | 值 |
|------|-----|
| DWD tick 数 | {stats['tick_count']} |
| ODS 原始记录 | {stats['ods_count']} |
| 去重率 | {stats['dedup_ratio']:.1f}% |
| 平均延迟 | {stats['avg_latency']:.1f} ms |
| P50 延迟 | {stats['p50_latency']:.1f} ms |
| P95 延迟 | {stats['p95_latency']:.1f} ms |
| 最大延迟 | {stats['max_latency']:.1f} ms |
| >500ms 次数 | {stats['latency_gt_500']} |
| >1000ms 次数 | {stats['latency_gt_1000']} |

"""

    # System health summary
    report += """## 系统健康度评估

"""
    health_items = []

    # Check dedup effectiveness
    if dwd_count > 0 and expected_ticks > 0:
        dedup_rate = overall_dedup
        if dedup_rate > 30:
            health_items.append(f"- **去重有效**: DWD 去重率 {dedup_rate:.1f}%，存储优化显著")
        elif dedup_rate > 0:
            health_items.append(f"- **去重正常**: DWD 去重率 {dedup_rate:.1f}%")
        else:
            health_items.append(f"- **数据活跃**: 去重率 {dedup_rate:.1f}%，标的交易频繁")

    # Check latency
    all_stats = [analyze_symbol(conn, s, date) for s in symbols]
    valid_stats = [s for s in all_stats if s]
    if valid_stats:
        avg_lat = sum(s['avg_latency'] for s in valid_stats) / len(valid_stats)
        max_lat = max(s['max_latency'] for s in valid_stats)
        if avg_lat < 100:
            health_items.append(f"- **延迟优秀**: 平均延迟 {avg_lat:.1f}ms")
        elif avg_lat < 500:
            health_items.append(f"- **延迟正常**: 平均延迟 {avg_lat:.1f}ms")
        else:
            health_items.append(f"- **延迟偏高**: 平均延迟 {avg_lat:.1f}ms，建议检查网络")

        if max_lat > 2000:
            health_items.append(f"- **存在毛刺**: 最大延迟 {max_lat:.0f}ms")

    # Check data completeness
    if valid_stats:
        total_ticks = sum(s['tick_count'] for s in valid_stats)
        total_ods = sum(s['ods_count'] for s in valid_stats)
        if total_ods > 0:
            completeness = total_ticks / total_ods * 100
            health_items.append(f"- **数据完整度**: {completeness:.1f}%")

    if not health_items:
        health_items.append("- 无数据可供评估")

    report += "\n".join(health_items) + "\n"

    return report

def main():
    parser = argparse.ArgumentParser(description="行情数据分析")
    parser.add_argument('--config', '-c', default=None, help='配置文件路径')
    parser.add_argument('--date', default=None, help='分析日期 (YYYY-MM-DD)')
    parser.add_argument('--symbol', '-s', nargs='+', help='分析指定标的')
    parser.add_argument('--output', '-o', default=None, help='输出文件路径')
    args = parser.parse_args()

    config = load_config(args.config)
    db_path = config['database']['path']

    if not Path(db_path).exists():
        print(f"数据库不存在: {db_path}")
        return 1

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    symbols = args.symbol or config['symbols']
    report = generate_report(conn, config, args.date, symbols)

    if args.output:
        Path(args.output).write_text(report, encoding='utf-8')
        print(f"报告已生成: {args.output}")
    else:
        print(report)

    conn.close()
    return 0

if __name__ == "__main__":
    sys.exit(main() or 0)
