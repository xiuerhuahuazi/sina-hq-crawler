import pytest
from unittest.mock import patch, MagicMock
import requests
from src.fetcher import QuoteFetcher


class TestQuoteFetcher:
    def test_init(self, base_config):
        fetcher = QuoteFetcher(base_config)
        assert fetcher._api_url == base_config['http']['api_url']
        assert fetcher._timeout == base_config['http']['timeout']
        fetcher.close()

    def test_context_manager(self, base_config):
        with QuoteFetcher(base_config) as fetcher:
            assert fetcher._session is not None

    @patch('src.fetcher.requests.Session')
    def test_fetch_success(self, mock_session_cls, base_config):
        mock_resp = MagicMock()
        mock_resp.text = 'var hq_str_sh000001="上证指数,4044.8292,..."'
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()

        mock_session = MagicMock()
        mock_session.get.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        fetcher = QuoteFetcher(base_config)
        text, status, latency = fetcher.fetch(["sh000001"])

        assert text == mock_resp.text
        assert status == 200
        assert latency >= 0
        mock_session.get.assert_called_once()
        fetcher.close()

    @patch('src.fetcher.requests.Session')
    @patch('src.fetcher.time.sleep')
    def test_fetch_with_retry_success_on_second(self, mock_sleep, mock_session_cls, base_config):
        mock_resp = MagicMock()
        mock_resp.text = "data"
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()

        mock_session = MagicMock()
        mock_session.get.side_effect = [requests.Timeout("timeout"), mock_resp]
        mock_session_cls.return_value = mock_session

        fetcher = QuoteFetcher(base_config)
        text, status, latency = fetcher.fetch_with_retry(["sh000001"])
        assert text == "data"
        assert status == 200
        mock_sleep.assert_called_once()
        fetcher.close()

    @patch('src.fetcher.requests.Session')
    @patch('src.fetcher.time.sleep')
    def test_fetch_with_retry_all_fail(self, mock_sleep, mock_session_cls, base_config):
        mock_session = MagicMock()
        mock_session.get.side_effect = requests.ConnectionError("fail")
        mock_session_cls.return_value = mock_session

        fetcher = QuoteFetcher(base_config)
        with pytest.raises(requests.ConnectionError):
            fetcher.fetch_with_retry(["sh000001"])
        # max_retries=2 => 3 attempts total => 2 sleeps
        assert mock_sleep.call_count == 2
        fetcher.close()

    @patch('src.fetcher.requests.Session')
    def test_fetch_http_error_raises(self, mock_session_cls, base_config):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.HTTPError("403")

        mock_session = MagicMock()
        mock_session.get.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        fetcher = QuoteFetcher(base_config)
        with pytest.raises(requests.HTTPError):
            fetcher.fetch(["sh000001"])
        fetcher.close()

    @patch('src.fetcher.requests.Session')
    def test_close(self, mock_session_cls, base_config):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session

        fetcher = QuoteFetcher(base_config)
        fetcher.close()
        mock_session.close.assert_called_once()
