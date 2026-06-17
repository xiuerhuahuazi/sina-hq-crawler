import time
import signal
import logging
import math
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Queue

logger = logging.getLogger(__name__)

class CrawlScheduler:
    def __init__(self, config: dict, storage, fetcher, parser, monitor=None,
                 register_signals=True):
        self._config = config
        self._storage = storage
        self._fetcher = fetcher
        self._parser = parser
        self._monitor = monitor
        self._shutdown = False
        self._force_exit = False

        self._poll_interval = config['crawl']['poll_interval']
        self._test_duration = config['crawl']['test_duration']
        self._symbols = list(config['symbols'])

        # Concurrency settings
        self._concurrency_mode = config['concurrency']['enabled']
        self._max_workers = config['concurrency']['max_workers']
        self._auto_threshold = config['concurrency']['auto_threshold']
        self._batch_size = config['concurrency']['batch_size']

        # Stats
        self._round_count = 0
        self._success_count = 0
        self._fail_count = 0
        self._start_time = None

        # Signal handlers (skip when managed by daemon)
        if register_signals:
            signal.signal(signal.SIGINT, self._handle_signal)
            signal.signal(signal.SIGTERM, self._handle_signal)

    def _handle_signal(self, signum, frame):
        if self._shutdown:
            logger.warning("Force exit requested")
            self._force_exit = True
        else:
            logger.info("Graceful shutdown initiated (signal %d)", signum)
            self._shutdown = True

    def stop(self):
        """外部可控停止（daemon 在时段结束时调用）。"""
        self._shutdown = True

    @property
    def is_running(self) -> bool:
        return self._start_time is not None and not self._shutdown

    def _decide_concurrency(self) -> tuple[int, list[list[str]]]:
        """Decide thread count and symbol batches."""
        n = len(self._symbols)

        if self._concurrency_mode == 'false' or self._concurrency_mode is False:
            return 1, [self._symbols]

        if self._concurrency_mode == 'auto':
            if n < self._auto_threshold:
                return 1, [self._symbols]

        # Both 'true' and 'auto' (when threshold met) use this logic
        workers = min(math.ceil(n / self._batch_size), self._max_workers)
        workers = max(workers, 1)

        batches = []
        for i in range(0, n, self._batch_size):
            batches.append(self._symbols[i:i + self._batch_size])

        return workers, batches

    def run(self, symbols=None, end_time=None):
        """Main polling loop.

        Parameters
        ----------
        symbols : list[str] | None
            Override self._symbols (daemon passes current session symbols).
        end_time : datetime | None
            When set, scheduler exits when datetime.now() >= end_time.
        """
        if symbols is not None:
            self._symbols = list(symbols)

        self._start_time = time.time()
        workers, batches = self._decide_concurrency()

        logger.info("Starting crawler: %d symbols, %d thread(s), %d batch(es), interval %ds",
                     len(self._symbols), workers, len(batches), self._poll_interval)

        if end_time:
            logger.info("End time: %s", end_time.strftime("%H:%M:%S"))
        elif self._test_duration > 0:
            logger.info("Test duration: %ds", self._test_duration)
        else:
            logger.info("Running until interrupted")

        try:
            while not self._force_exit:
                if self._shutdown:
                    break

                # Check end_time (daemon session boundary)
                if end_time and datetime.now() >= end_time:
                    logger.info("End time reached (%s)", end_time.strftime("%H:%M:%S"))
                    break

                if self._test_duration > 0:
                    elapsed = time.time() - self._start_time
                    if elapsed >= self._test_duration:
                        logger.info("Test duration reached (%.0fs)", elapsed)
                        break

                self._round_count += 1

                if workers == 1:
                    # Single-threaded path
                    self._fetch_and_store_batch(self._symbols, 1, len(batches))
                else:
                    # Multi-threaded: threads fetch, main thread stores
                    _queue = Queue()

                    with ThreadPoolExecutor(max_workers=workers) as pool:
                        futures = []
                        for i, batch in enumerate(batches):
                            future = pool.submit(self._fetch_batch, batch)
                            futures.append(future)

                        for future in as_completed(futures):
                            try:
                                result = future.result()
                                if result:
                                    raw_text, quotes, status_code, latency_ms, url = result
                                    self._storage.store(raw_text, quotes, status_code, latency_ms, url)
                                    self._success_count += len(quotes)
                            except Exception as e:
                                self._fail_count += 1
                                logger.error("Fetch failed: %s", e)
                                if self._monitor:
                                    self._monitor.on_fetch_error(e)

                # Check for data gaps
                if self._monitor:
                    self._monitor.check_gaps(self._symbols)

                time.sleep(self._poll_interval)

        except Exception as e:
            logger.error("Unexpected error in main loop: %s", e)
        finally:
            self._cleanup()

    def _fetch_batch(self, symbols: list[str]):
        """Fetch a batch of symbols (runs in thread)."""
        try:
            raw_text, status_code, latency_ms = self._fetcher.fetch_with_retry(symbols)
            quotes = self._parser(raw_text)
            return raw_text, quotes, status_code, latency_ms, ""
        except Exception as e:
            logger.error("Fetch batch failed: %s", e)
            if self._monitor:
                self._monitor.on_fetch_error(e)
            return None

    def _fetch_and_store_batch(self, symbols: list[str], batch_idx: int, total_batches: int):
        """Single-threaded fetch and store."""
        try:
            raw_text, status_code, latency_ms = self._fetcher.fetch_with_retry(symbols)
            quotes = self._parser(raw_text)
            self._storage.store(raw_text, quotes, status_code, latency_ms)
            self._success_count += len(quotes)

            # Log tick info
            for q in quotes:
                prev_close = q.get('prev_close')
                current = q['current']
                change_pct = 0
                if prev_close and current and prev_close != 0:
                    change_pct = (current / prev_close - 1) * 100
                sign = "+" if change_pct >= 0 else ""
                logger.info("[%d] %s %s current:%.4f change:%s%.2f%% latency:%.1fms",
                            self._round_count, q['symbol'], q['name'] or '',
                            current or 0, sign, change_pct, latency_ms)

        except Exception as e:
            self._fail_count += 1
            logger.error("[%d] Fetch failed: %s", self._round_count, e)
            if self._monitor:
                self._monitor.on_fetch_error(e)

    def _cleanup(self):
        """Graceful shutdown: flush storage, compute daily summary."""
        logger.info("Shutting down...")

        try:
            self._storage.finalize()
        except Exception as e:
            logger.error("Finalize failed: %s", e)

        elapsed = time.time() - self._start_time if self._start_time else 0
        stats = self._storage.get_stats()

        logger.info("=== Crawl Complete ===")
        logger.info("Duration: %.0fs | Rounds: %d | Success: %d | Fail: %d",
                     elapsed, self._round_count, self._success_count, self._fail_count)
        logger.info("Total ticks stored: %d", stats.get('total_ticks', 0))

        if self._monitor:
            monitor_stats = self._monitor.get_stats()
            logger.info("Monitor: %d ticks tracked, %d alerts",
                        monitor_stats.get('total_ticks', 0), monitor_stats.get('total_alerts', 0))

    def get_stats(self) -> dict:
        elapsed = time.time() - self._start_time if self._start_time else 0
        return {
            'rounds': self._round_count,
            'success': self._success_count,
            'failures': self._fail_count,
            'elapsed': elapsed,
        }
