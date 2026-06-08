import signal
import pytest
from unittest.mock import MagicMock, patch
from src.scheduler import CrawlScheduler


def make_scheduler(base_config, **overrides):
    for k, v in overrides.items():
        if '.' in k:
            parts = k.split('.')
            base_config[parts[0]][parts[1]] = v
        else:
            base_config[k] = v
    storage = MagicMock()
    storage.finalize = MagicMock()
    storage.get_stats = MagicMock(return_value={'total_ticks': 0})
    storage.store = MagicMock()
    fetcher = MagicMock()
    fetcher.fetch_with_retry = MagicMock(return_value=("raw", 200, 25.0))
    parser = MagicMock()
    parser.parse_response = MagicMock(return_value=[])
    monitor = MagicMock()
    sched = CrawlScheduler(base_config, storage, fetcher, parser, monitor)
    return sched, storage, fetcher, parser, monitor


class TestDecideConcurrency:
    def test_false_mode_single_thread(self, base_config):
        sched, *_ = make_scheduler(base_config, **{"concurrency.enabled": "false"})
        workers, batches = sched._decide_concurrency()
        assert workers == 1
        assert len(batches) == 1

    def test_auto_below_threshold(self, base_config):
        sched, *_ = make_scheduler(base_config, **{"concurrency.enabled": "auto"})
        # 2 symbols < threshold of 6
        workers, batches = sched._decide_concurrency()
        assert workers == 1
        assert len(batches) == 1

    def test_auto_above_threshold(self, base_config):
        base_config['symbols'] = [f"sh{i:06d}" for i in range(10)]
        base_config['concurrency']['enabled'] = 'auto'
        base_config['concurrency']['auto_threshold'] = 6
        base_config['concurrency']['batch_size'] = 4
        base_config['concurrency']['max_workers'] = 4
        sched, *_ = make_scheduler(base_config)
        workers, batches = sched._decide_concurrency()
        assert workers > 1
        assert len(batches) > 1

    def test_true_mode_multi_thread(self, base_config):
        base_config['symbols'] = [f"sh{i:06d}" for i in range(10)]
        base_config['concurrency']['enabled'] = 'true'
        base_config['concurrency']['batch_size'] = 4
        base_config['concurrency']['max_workers'] = 4
        sched, *_ = make_scheduler(base_config)
        workers, batches = sched._decide_concurrency()
        assert workers > 1

    def test_single_symbol_single_thread(self, base_config):
        base_config['symbols'] = ['sh000001']
        base_config['concurrency']['enabled'] = 'true'
        sched, *_ = make_scheduler(base_config)
        workers, batches = sched._decide_concurrency()
        assert workers == 1
        assert len(batches) == 1


class TestSignalHandling:
    def test_first_signal_graceful(self, base_config):
        sched, *_ = make_scheduler(base_config)
        assert sched._shutdown is False
        sched._handle_signal(signal.SIGINT, None)
        assert sched._shutdown is True
        assert sched._force_exit is False

    def test_second_signal_force(self, base_config):
        sched, *_ = make_scheduler(base_config)
        sched._handle_signal(signal.SIGINT, None)
        sched._handle_signal(signal.SIGINT, None)
        assert sched._force_exit is True


class TestRunLoop:
    def test_duration_exits(self, base_config):
        base_config['crawl']['test_duration'] = 0.1
        base_config['crawl']['poll_interval'] = 0.05
        sched, storage, fetcher, parser, monitor = make_scheduler(base_config)
        sched.run()
        stats = sched.get_stats()
        assert stats['rounds'] >= 1
        storage.finalize.assert_called()

    def test_shutdown_exits(self, base_config):
        base_config['crawl']['test_duration'] = 0
        base_config['crawl']['poll_interval'] = 0.05
        sched, storage, fetcher, parser, monitor = make_scheduler(base_config)
        sched._shutdown = True  # pre-set shutdown
        sched.run()
        storage.finalize.assert_called()

    def test_get_stats(self, base_config):
        sched, *_ = make_scheduler(base_config)
        stats = sched.get_stats()
        assert 'rounds' in stats
        assert 'success' in stats
        assert 'failures' in stats
        assert 'elapsed' in stats


class TestMultiThreadedRun:
    def test_multi_thread_duration_exits(self, base_config):
        base_config['symbols'] = [f"sh{i:06d}" for i in range(10)]
        base_config['concurrency']['enabled'] = 'true'
        base_config['concurrency']['batch_size'] = 4
        base_config['concurrency']['max_workers'] = 4
        base_config['crawl']['test_duration'] = 0.1
        base_config['crawl']['poll_interval'] = 0.05
        sched, storage, fetcher, parser, monitor = make_scheduler(base_config)
        sched.run()
        stats = sched.get_stats()
        assert stats['rounds'] >= 1
        storage.finalize.assert_called()

    def test_multi_thread_with_real_quotes(self, base_config):
        base_config['symbols'] = [f"sh{i:06d}" for i in range(10)]
        base_config['concurrency']['enabled'] = 'true'
        base_config['concurrency']['batch_size'] = 5
        base_config['concurrency']['max_workers'] = 2
        base_config['crawl']['test_duration'] = 0.1
        base_config['crawl']['poll_interval'] = 0.05
        sched, storage, fetcher, parser, monitor = make_scheduler(base_config)
        # Provide real parsed quotes
        parser.return_value = [
            {"symbol": "sh000001", "name": "上证指数", "current": 4000.0,
             "prev_close": 3900.0, "open": 3950.0, "high": 4010.0, "low": 3940.0,
             "volume": 100000, "amount": 500000000, "quote_date": "2026-06-05",
             "quote_time": "10:00:00", "order_book": None}
        ]
        sched.run()
        assert storage.store.call_count >= 1


class TestFetchBatch:
    def test_fetch_batch_success(self, base_config):
        sched, storage, fetcher, parser, monitor = make_scheduler(base_config)
        result = sched._fetch_batch(["sh000001"])
        assert result is not None
        assert len(result) == 5

    def test_fetch_batch_failure(self, base_config):
        sched, storage, fetcher, parser, monitor = make_scheduler(base_config)
        fetcher.fetch_with_retry.side_effect = Exception("fail")
        result = sched._fetch_batch(["sh000001"])
        assert result is None
        monitor.on_fetch_error.assert_called()


class TestFetchAndStoreBatch:
    def test_single_thread_fetch_and_store(self, base_config):
        sched, storage, fetcher, parser, monitor = make_scheduler(base_config)
        sched._round_count = 1
        sched._fetch_and_store_batch(["sh000001"], 1, 1)
        storage.store.assert_called()

    def test_single_thread_with_parsed_quotes(self, base_config):
        sched, storage, fetcher, parser, monitor = make_scheduler(base_config)
        sched._round_count = 1
        parser.return_value = [
            {"symbol": "sh000001", "name": "上证指数", "current": 4000.0,
             "prev_close": 3900.0, "open": 3950.0, "high": 4010.0, "low": 3940.0,
             "volume": 100000, "amount": 500000000, "quote_date": "2026-06-05",
             "quote_time": "10:00:00", "order_book": None}
        ]
        sched._fetch_and_store_batch(["sh000001"], 1, 1)
        storage.store.assert_called()
        assert sched._success_count == 1

    def test_single_thread_failure(self, base_config):
        sched, storage, fetcher, parser, monitor = make_scheduler(base_config)
        sched._round_count = 1
        fetcher.fetch_with_retry.side_effect = Exception("fail")
        sched._fetch_and_store_batch(["sh000001"], 1, 1)
        assert sched._fail_count == 1
        monitor.on_fetch_error.assert_called()
