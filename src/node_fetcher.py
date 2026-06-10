"""节点数据抓取器 — 调用 Market_Center.getHQNodeData API。"""

import logging
import requests

logger = logging.getLogger(__name__)

_BASE_URL = (
    "https://vip.stock.finance.sina.com.cn"
    "/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
)


class NodeDataFetcher:
    """抓取行情中心列表数据（含 per/pb/mktcap/nmc/turnoverratio）。"""

    def __init__(self, config: dict) -> None:
        self._timeout = config.get("http", {}).get("timeout", 10)
        self._headers = {
            "Referer": "https://vip.stock.finance.sina.com.cn/",
            "User-Agent": config.get("http", {}).get("headers", {}).get(
                "User-Agent",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            ),
        }
        self._session = requests.Session()
        self._session.headers.update(self._headers)

    def fetch_node(
        self,
        node: str,
        sort: str = "symbol",
        asc: int = 1,
        page: int = 1,
        num: int = 80,
    ) -> list[dict]:
        """获取指定节点的一页数据。"""
        params = {
            "node": node,
            "sort": sort,
            "asc": asc,
            "page": page,
            "num": num,
        }
        resp = self._session.get(_BASE_URL, params=params, timeout=self._timeout)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return data
        return []

    def fetch_all(self, node: str, sort: str = "symbol",
                  asc: int = 1, num: int = 80) -> list[dict]:
        """分页获取指定节点的全部数据。"""
        all_data: list[dict] = []
        page = 1
        while True:
            batch = self.fetch_node(node, sort=sort, asc=asc, page=page, num=num)
            if not batch:
                break
            all_data.extend(batch)
            if len(batch) < num:
                break
            page += 1
        logger.info("节点 %s: 共获取 %d 条数据 (%d 页)", node, len(all_data), page)
        return all_data

    def close(self) -> None:
        self._session.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
