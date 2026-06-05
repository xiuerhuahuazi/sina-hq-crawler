#!/usr/bin/env python3
"""新浪财经实时行情采集器 — 数据仓库分层架构"""

import argparse
import sys
import logging

from src.config import load_config
from src.logger import setup_logging
from src.db import init_db
from src.fetcher import QuoteFetcher
from src.parser import parse_response
from src.storage import QuoteStorage
from src.scheduler import CrawlScheduler
from src.monitor import QuoteMonitor

logger = logging.getLogger(__name__)

def parse_args():
    parser = argparse.ArgumentParser(description="新浪财经实时行情采集器")
    parser.add_argument('--config', '-c', default=None, help='配置文件路径 (默认: config.yaml)')
    parser.add_argument('--symbols', '-s', nargs='+', help='覆盖配置中的标的列表')
    parser.add_argument('--duration', '-d', type=int, help='覆盖测试时长（秒）')
    parser.add_argument('--dry-run', action='store_true', help='只加载配置并验证，不启动采集')
    return parser.parse_args()

def main():
    args = parse_args()

    # Load config
    config = load_config(args.config)

    # Override from CLI
    if args.symbols:
        config['symbols'] = args.symbols
    if args.duration is not None:
        config['crawl']['test_duration'] = args.duration

    # Setup logging
    setup_logging(config)

    # Print config summary
    logger.info("=== 新浪行情采集器启动 ===")
    logger.info("标的: %s", ', '.join(config['symbols']))
    logger.info("轮询间隔: %ds | 测试时长: %s",
                config['crawl']['poll_interval'],
                f"{config['crawl']['test_duration']}s" if config['crawl']['test_duration'] > 0 else "无限")
    logger.info("并发模式: %s", config['concurrency']['enabled'])
    logger.info("数据库: %s", config['database']['path'])

    if args.dry_run:
        logger.info("Dry run: 配置验证通过")
        # Validate parser with a test fetch
        with QuoteFetcher(config) as fetcher:
            try:
                raw, status, latency = fetcher.fetch(config['symbols'])
                quotes = parse_response(raw)
                logger.info("Dry run: 成功获取 %d 条数据 (%.1fms)", len(quotes), latency)
                for q in quotes:
                    logger.info("  %s %s: %.4f", q['symbol'], q['name'], q['current'] or 0)
            except Exception as e:
                logger.error("Dry run: 获取失败: %s", e)
                sys.exit(1)
        return

    # Initialize components
    db_path = config['database']['path']
    conn = init_db(db_path, config)

    monitor = QuoteMonitor(config) if config['monitor']['enabled'] else None

    with QuoteFetcher(config) as fetcher:
        storage = QuoteStorage(conn, config, monitor)
        scheduler = CrawlScheduler(config, storage, fetcher, parse_response, monitor)
        scheduler.run()

    conn.close()
    logger.info("采集器已退出")

if __name__ == "__main__":
    main()
