import pytest
from unittest.mock import patch, MagicMock
from src.crawler import parse_args, main


class TestParseArgs:
    def test_no_args(self):
        with patch('sys.argv', ['crawl']):
            args = parse_args()
            assert args.config is None
            assert args.symbols is None
            assert args.duration is None
            assert args.dry_run is False

    def test_symbols_arg(self):
        with patch('sys.argv', ['crawl', '--symbols', 'sh000001', 'bj920576']):
            args = parse_args()
            assert args.symbols == ['sh000001', 'bj920576']

    def test_duration_arg(self):
        with patch('sys.argv', ['crawl', '--duration', '60']):
            args = parse_args()
            assert args.duration == 60

    def test_config_arg(self):
        with patch('sys.argv', ['crawl', '--config', '/tmp/cfg.yaml']):
            args = parse_args()
            assert args.config == '/tmp/cfg.yaml'

    def test_dry_run_flag(self):
        with patch('sys.argv', ['crawl', '--dry-run']):
            args = parse_args()
            assert args.dry_run is True

    def test_short_args(self):
        with patch('sys.argv', ['crawl', '-c', '/tmp/c.yaml', '-s', 'sh000001', '-d', '10']):
            args = parse_args()
            assert args.config == '/tmp/c.yaml'
            assert args.symbols == ['sh000001']
            assert args.duration == 10


class TestMain:
    def test_dry_run_success(self, tmp_path, base_config):
        cfg_file = tmp_path / "cfg.yaml"
        cfg_file.write_text("symbols:\n  - sh000001\n", encoding="utf-8")
        mock_raw = 'var hq_str_sh000001="上证指数,4044.8292,4057.7811,4042.6525,4078.9317,4038.0447,0,0,559541192,1151469946916,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,2026-06-05,14:19:41,00,"'
        with patch('sys.argv', ['crawl', '--config', str(cfg_file), '--dry-run']), \
             patch('src.crawler.QuoteFetcher') as MockFetcher:
            mock_fetcher = MagicMock()
            mock_fetcher.__enter__ = MagicMock(return_value=mock_fetcher)
            mock_fetcher.__exit__ = MagicMock(return_value=False)
            mock_fetcher.fetch.return_value = (mock_raw, 200, 25.0)
            MockFetcher.return_value = mock_fetcher
            main()

    def test_dry_run_fetch_failure(self, tmp_path):
        cfg_file = tmp_path / "cfg.yaml"
        cfg_file.write_text("symbols:\n  - sh000001\n", encoding="utf-8")
        with patch('sys.argv', ['crawl', '--config', str(cfg_file), '--dry-run']), \
             patch('src.crawler.QuoteFetcher') as MockFetcher:
            mock_fetcher = MagicMock()
            mock_fetcher.__enter__ = MagicMock(return_value=mock_fetcher)
            mock_fetcher.__exit__ = MagicMock(return_value=False)
            mock_fetcher.fetch.side_effect = Exception("network error")
            MockFetcher.return_value = mock_fetcher
            with pytest.raises(SystemExit):
                main()

    def test_symbols_override(self, tmp_path):
        cfg_file = tmp_path / "cfg.yaml"
        cfg_file.write_text("symbols:\n  - sh000001\n", encoding="utf-8")
        mock_raw = 'var hq_str_bj920576="天力复合,58.390,56.840,69.690,70.510,57.700,69.600,300,69.470,7765,69.460,59,69.430,1100,69.420,99,69.690,158,69.700,5186,69.720,1700,69.740,16557,69.750,1042,69.750,2026-06-05,14:29:51,00,304.9356,0.0000,0,8300000,B,T"'
        with patch('sys.argv', ['crawl', '--config', str(cfg_file), '--symbols', 'bj920576', '--dry-run']), \
             patch('src.crawler.QuoteFetcher') as MockFetcher:
            mock_fetcher = MagicMock()
            mock_fetcher.__enter__ = MagicMock(return_value=mock_fetcher)
            mock_fetcher.__exit__ = MagicMock(return_value=False)
            mock_fetcher.fetch.return_value = (mock_raw, 200, 30.0)
            MockFetcher.return_value = mock_fetcher
            main()

    def test_normal_crawl_flow(self, tmp_path):
        cfg_file = tmp_path / "cfg.yaml"
        cfg_file.write_text(
            "symbols:\n  - sh000001\ncrawl:\n  test_duration: 0.1\n  poll_interval: 0.05\n",
            encoding="utf-8"
        )
        with patch('sys.argv', ['crawl', '--config', str(cfg_file)]), \
             patch('src.crawler.QuoteFetcher') as MockFetcher, \
             patch('src.crawler.CrawlScheduler') as MockScheduler:
            mock_fetcher = MagicMock()
            mock_fetcher.__enter__ = MagicMock(return_value=mock_fetcher)
            mock_fetcher.__exit__ = MagicMock(return_value=False)
            MockFetcher.return_value = mock_fetcher

            mock_scheduler = MagicMock()
            MockScheduler.return_value = mock_scheduler

            main()
            mock_scheduler.run.assert_called_once()

    def test_monitor_disabled(self, tmp_path):
        cfg_file = tmp_path / "cfg.yaml"
        cfg_file.write_text(
            "symbols:\n  - sh000001\nmonitor:\n  enabled: false\ncrawl:\n  test_duration: 0.1\n  poll_interval: 0.05\n",
            encoding="utf-8"
        )
        with patch('sys.argv', ['crawl', '--config', str(cfg_file)]), \
             patch('src.crawler.QuoteFetcher') as MockFetcher, \
             patch('src.crawler.CrawlScheduler') as MockScheduler:
            mock_fetcher = MagicMock()
            mock_fetcher.__enter__ = MagicMock(return_value=mock_fetcher)
            mock_fetcher.__exit__ = MagicMock(return_value=False)
            MockFetcher.return_value = mock_fetcher

            mock_scheduler = MagicMock()
            MockScheduler.return_value = mock_scheduler

            main()
            # Verify scheduler was created (monitor=None path)
            MockScheduler.assert_called_once()
            call_args = MockScheduler.call_args
            assert call_args[0][4] is None  # monitor=None
