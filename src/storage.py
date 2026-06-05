import time
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class QuoteStorage:
    def __init__(self, conn, config: dict, monitor=None):
        self._conn = conn
        self._batch_size = config['crawl']['batch_commit_size']
        self._commit_interval = config['crawl']['batch_commit_interval']
        self._monitor = monitor
        self._pending_ods = []
        self._pending_dwd = []
        self._last_commit_time = time.monotonic()
        # In-memory cache for dedup: symbol -> {current, volume, high, low, amount}
        self._last_values = {}
        # Tick index counter per symbol per session
        self._tick_counters = {}
        # Track previous volume/amount for delta calculation
        self._prev_volume = {}
        self._prev_amount = {}

    def store(self, raw_text: str, quotes: list[dict], status_code: int, latency_ms: float, url: str = ""):
        """Store raw response (ODS) and parsed quotes (DWD)."""
        now = datetime.now().isoformat()

        # ODS: always insert
        parse_ok = 1 if quotes else 0
        symbols_in = ",".join(q['symbol'] for q in quotes) if quotes else ""
        self._pending_ods.append((now, url, status_code, raw_text, latency_ms, parse_ok, None, symbols_in))

        # DWD: dedup check then insert
        for q in quotes:
            if self._should_insert(q):
                dwd_row = self._build_dwd_row(q, latency_ms, now)
                self._pending_dwd.append(dwd_row)

                # Update DWS minute bar
                self._update_minute_bar(q, dwd_row)

                # Notify monitor
                if self._monitor:
                    self._monitor.on_tick(q['symbol'], q['current'], q.get('prev_close'), latency_ms)

        self._maybe_commit()

    def _should_insert(self, q: dict) -> bool:
        """Check if this tick differs from the last one for this symbol."""
        symbol = q['symbol']
        if symbol not in self._last_values:
            return True  # First tick always insert
        last = self._last_values[symbol]
        return (
            q['current'] != last.get('current') or
            q['volume'] != last.get('volume') or
            q['high'] != last.get('high') or
            q['low'] != last.get('low')
        )

    def _build_dwd_row(self, q: dict, latency_ms: float, fetched_at: str) -> tuple:
        """Build a DWD row tuple for INSERT."""
        symbol = q['symbol']
        current = q['current']
        prev_close = q.get('prev_close')
        volume = q['volume']
        amount = q['amount']

        # Change percentage
        change_pct = None
        if prev_close and current and prev_close != 0:
            change_pct = (current / prev_close - 1) * 100

        # Delta volume/amount
        prev_vol = self._prev_volume.get(symbol, 0) or 0
        prev_amt = self._prev_amount.get(symbol, 0) or 0
        cur_vol = volume or 0
        cur_amt = amount or 0
        delta_volume = cur_vol - prev_vol if cur_vol else 0
        delta_amount = cur_amt - prev_amt if cur_amt else 0

        # Tick index
        idx = self._tick_counters.get(symbol, 0) + 1
        self._tick_counters[symbol] = idx
        is_first = 1 if idx == 1 else 0

        # Update caches
        self._last_values[symbol] = {
            'current': current, 'volume': volume, 'high': q['high'], 'low': q['low']
        }
        if volume:
            self._prev_volume[symbol] = volume
        if amount:
            self._prev_amount[symbol] = amount

        return (
            symbol, q['name'], q.get('quote_date'), q.get('quote_time'),
            q['open'], prev_close, current, q['high'], q['low'],
            volume, amount, change_pct, delta_volume, delta_amount,
            idx, q.get('order_book'), fetched_at, latency_ms, is_first
        )

    def _update_minute_bar(self, q: dict, dwd_row: tuple):
        """Upsert minute bar in DWS."""
        symbol = q['symbol']
        now = datetime.now()
        bar_minute = now.strftime('%Y-%m-%d %H:%M')

        try:
            self._conn.execute("""
                INSERT INTO dws_minute_bars (symbol, bar_minute, open, high, low, close, volume, amount, tick_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(symbol, bar_minute) DO UPDATE SET
                    high = MAX(dws_minute_bars.high, excluded.high),
                    low = MIN(dws_minute_bars.low, excluded.low),
                    close = excluded.close,
                    volume = dws_minute_bars.volume + excluded.volume,
                    amount = dws_minute_bars.amount + excluded.amount,
                    tick_count = dws_minute_bars.tick_count + 1
            """, (symbol, bar_minute, q['open'], q['high'], q['low'], q['current'],
                  dwd_row[12] or 0, dwd_row[13] or 0))  # delta_volume, delta_amount
        except Exception as e:
            logger.debug("Minute bar update failed: %s", e)

    def _maybe_commit(self):
        now = time.monotonic()
        size_reached = len(self._pending_dwd) >= self._batch_size
        time_reached = (now - self._last_commit_time) >= self._commit_interval
        if size_reached or time_reached:
            self.flush()

    def flush(self):
        """Write all buffered rows and commit."""
        if not self._pending_ods and not self._pending_dwd:
            return

        try:
            if self._pending_ods:
                self._conn.executemany(
                    "INSERT INTO ods_raw_quotes (request_ts, url, status_code, raw_text, latency_ms, parse_ok, error_detail, symbols_in) VALUES (?,?,?,?,?,?,?,?)",
                    self._pending_ods
                )
            if self._pending_dwd:
                self._conn.executemany(
                    "INSERT INTO dwd_quotes (symbol, name, quote_date, quote_time, open, prev_close, current, high, low, volume, amount, change_pct, delta_volume, delta_amount, tick_index, order_book, fetched_at, latency_ms, is_first_tick) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    self._pending_dwd
                )
            self._conn.commit()
            logger.debug("Flushed %d ODS + %d DWD rows", len(self._pending_ods), len(self._pending_dwd))
        except Exception as e:
            logger.error("Flush failed: %s", e)
            self._conn.rollback()

        self._pending_ods.clear()
        self._pending_dwd.clear()
        self._last_commit_time = time.monotonic()

    def finalize(self):
        """Compute dws_daily_summary from DWD data at session end."""
        self.flush()
        try:
            self._conn.execute("""
                INSERT OR REPLACE INTO dws_daily_summary
                SELECT symbol, quote_date,
                       (SELECT open FROM dwd_quotes d2 WHERE d2.symbol = d.symbol AND d2.quote_date = d.quote_date ORDER BY d2.fetched_at LIMIT 1),
                       MAX(high), MIN(low),
                       (SELECT current FROM dwd_quotes d2 WHERE d2.symbol = d.symbol AND d2.quote_date = d.quote_date ORDER BY d2.fetched_at DESC LIMIT 1),
                       prev_close, MAX(volume), MAX(amount),
                       (SELECT change_pct FROM dwd_quotes d2 WHERE d2.symbol = d.symbol AND d2.quote_date = d.quote_date ORDER BY d2.fetched_at DESC LIMIT 1),
                       COUNT(*), MIN(fetched_at), MAX(fetched_at), AVG(latency_ms)
                FROM dwd_quotes d
                WHERE quote_date = date('now', 'localtime')
                GROUP BY symbol, quote_date
            """)
            self._conn.commit()
            logger.info("Daily summary computed")
        except Exception as e:
            logger.error("Daily summary failed: %s", e)

    def get_stats(self) -> dict:
        """Return storage statistics."""
        return {
            'pending_ods': len(self._pending_ods),
            'pending_dwd': len(self._pending_dwd),
            'symbols_tracked': len(self._last_values),
            'total_ticks': sum(self._tick_counters.values()),
        }
