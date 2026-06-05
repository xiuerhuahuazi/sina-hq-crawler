import time
import pytest
from unittest.mock import patch
from src.monitor import QuoteMonitor


class TestQuoteMonitor:
    def test_on_tick_counts(self, base_config):
        mon = QuoteMonitor(base_config)
        mon.on_tick("sh000001", 4000.0, 3900.0, 50.0)
        mon.on_tick("sh000001", 4010.0, 3900.0, 60.0)
        stats = mon.get_stats()
        assert stats['total_ticks'] == 2

    def test_latency_warn_alert(self, base_config, capsys):
        mon = QuoteMonitor(base_config)
        mon.on_tick("sh000001", 4000.0, 3900.0, 600.0)  # > 500ms
        stats = mon.get_stats()
        assert stats['total_alerts'] >= 1
        assert stats['alert_counts'].get('WARNING', 0) >= 1

    def test_latency_critical_alert(self, base_config):
        mon = QuoteMonitor(base_config)
        mon.on_tick("sh000001", 4000.0, 3900.0, 2500.0)  # > 2000ms
        stats = mon.get_stats()
        assert stats['alert_counts'].get('CRITICAL', 0) >= 1

    def test_latency_no_alert_when_normal(self, base_config):
        mon = QuoteMonitor(base_config)
        mon.on_tick("sh000001", 4000.0, 3900.0, 50.0)
        stats = mon.get_stats()
        assert stats['total_alerts'] == 0

    def test_price_spike_alert(self, base_config):
        mon = QuoteMonitor(base_config)
        # 3% spike: prev_close=100, current=105 => 5% change
        mon.on_tick("sh000001", 105.0, 100.0, 50.0)
        stats = mon.get_stats()
        assert stats['alert_counts'].get('WARNING', 0) >= 1

    def test_price_no_spike_when_small(self, base_config):
        mon = QuoteMonitor(base_config)
        # 1% change, below 3% threshold
        mon.on_tick("sh000001", 101.0, 100.0, 50.0)
        stats = mon.get_stats()
        assert stats['total_alerts'] == 0

    def test_price_spike_skipped_when_prev_close_none(self, base_config):
        mon = QuoteMonitor(base_config)
        mon.on_tick("sh000001", 105.0, None, 50.0)
        stats = mon.get_stats()
        assert stats['total_alerts'] == 0

    def test_on_fetch_error_alert_after_3(self, base_config):
        mon = QuoteMonitor(base_config)
        mon.on_fetch_error(Exception("err1"))
        mon.on_fetch_error(Exception("err2"))
        assert mon.get_stats()['total_alerts'] == 0
        mon.on_fetch_error(Exception("err3"))
        assert mon.get_stats()['total_alerts'] >= 1
        assert mon.get_stats()['alert_counts'].get('CRITICAL', 0) >= 1

    def test_consecutive_failures_reset_on_tick(self, base_config):
        mon = QuoteMonitor(base_config)
        mon.on_fetch_error(Exception("err1"))
        mon.on_fetch_error(Exception("err2"))
        assert mon.get_stats()['consecutive_failures'] == 2
        mon.on_tick("sh000001", 4000.0, 3900.0, 50.0)
        assert mon.get_stats()['consecutive_failures'] == 0

    def test_disabled_monitor_noop(self, base_config):
        base_config['monitor']['enabled'] = False
        mon = QuoteMonitor(base_config)
        mon.on_tick("sh000001", 4000.0, 3900.0, 5000.0)
        mon.on_fetch_error(Exception("err"))
        mon.check_gaps(["sh000001"])
        stats = mon.get_stats()
        assert stats['total_ticks'] == 0
        assert stats['total_alerts'] == 0

    def test_check_gaps_alerts(self, base_config):
        base_config['monitor']['gap_threshold_seconds'] = 0.1
        mon = QuoteMonitor(base_config)
        mon.on_tick("sh000001", 4000.0, 3900.0, 50.0)
        time.sleep(0.2)
        mon.check_gaps(["sh000001"])
        stats = mon.get_stats()
        assert stats['alert_counts'].get('CRITICAL', 0) >= 1

    def test_check_gaps_no_alert_when_fresh(self, base_config):
        mon = QuoteMonitor(base_config)
        mon.on_tick("sh000001", 4000.0, 3900.0, 50.0)
        mon.check_gaps(["sh000001"])
        stats = mon.get_stats()
        assert stats['total_alerts'] == 0
