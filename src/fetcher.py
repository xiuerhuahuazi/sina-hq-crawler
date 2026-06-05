import time
import random
import logging
import requests

logger = logging.getLogger(__name__)

class QuoteFetcher:
    def __init__(self, config: dict):
        self._api_url = config['http']['api_url']
        self._timeout = config['http']['timeout']
        self._max_retries = config['http']['max_retries']
        self._retry_base_delay = config['http']['retry_base_delay']
        self._retry_max_delay = config['http']['retry_max_delay']
        self._headers = dict(config['http']['headers'])
        self._session = requests.Session()
        self._session.headers.update(self._headers)

    def fetch(self, symbols: list[str]) -> tuple[str, int, float]:
        """Single fetch attempt. Returns (raw_text, status_code, latency_ms)."""
        ts = int(time.time() * 1000)
        url = self._api_url.format(ts=ts, symbols=",".join(symbols))
        t0 = time.monotonic()
        resp = self._session.get(url, timeout=self._timeout)
        latency = (time.monotonic() - t0) * 1000
        resp.encoding = "gb2312"
        resp.raise_for_status()
        logger.debug("Fetched %d symbols in %.1fms (status %d)", len(symbols), latency, resp.status_code)
        return resp.text, resp.status_code, latency

    def fetch_with_retry(self, symbols: list[str]) -> tuple[str, int, float]:
        """Fetch with exponential backoff retry."""
        last_error = None
        for attempt in range(self._max_retries + 1):
            try:
                return self.fetch(symbols)
            except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as e:
                last_error = e
                if attempt < self._max_retries:
                    delay = min(self._retry_base_delay * (2 ** attempt), self._retry_max_delay)
                    jitter = random.uniform(0, delay * 0.1)
                    sleep_time = delay + jitter
                    logger.warning("Fetch failed (attempt %d/%d): %s, retrying in %.1fs",
                                   attempt + 1, self._max_retries + 1, e, sleep_time)
                    time.sleep(sleep_time)
        raise last_error

    def close(self):
        self._session.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
