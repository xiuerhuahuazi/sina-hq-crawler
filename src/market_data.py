"""市场数据加载器 — 抓取并存储节点数据 + 行业/概念分类。"""

import json
import logging
import sqlite3
from datetime import datetime

import requests

from src.node_fetcher import NodeDataFetcher
from src.node_parser import parse_node_data

logger = logging.getLogger(__name__)

_NODES_URL = (
    "https://vip.stock.finance.sina.com.cn"
    "/quotes_service/api/json_v2.php/Market_Center.getHQNodes"
)

# 默认采集的 A 股节点
_DEFAULT_NODES = ["hs_a"]
# 默认行业分类节点
_SW_NODES = [
    "sw_sysh", "sw_mt", "sw_mrhl", "sw_hb", "sw_dlsb", "sw_jdhy",
    "sw_yyhy", "sw_sphy", "sw_jrhy", "sw_fdc", "sw_txbh", "sw_jsj",
    "sw_cmn", "sw_qc", "sw_jxhy", "sw_jzjc", "sw_fzzs", "sw_nyhy",
    "sw_qghy", "sw_gfjs", "sw_ylfw", "sw_shh", "sw_jtys", "sw_dzqj",
    "sw_ylqx", "sw_bjhy", "sw_iron", "sw_xc", "sw_dl", "sw_mech",
    "sw_gysb",
]


class MarketDataLoader:
    """加载市场数据（节点行情 + 行业/概念分类）。"""

    def __init__(self, conn: sqlite3.Connection, config: dict) -> None:
        self._conn = conn
        self._config = config
        self._fetcher = NodeDataFetcher(config)

    def load_node_data(self, nodes: list[str] | None = None) -> int:
        """抓取指定节点的数据并存入 dwd_node_data。返回总条数。"""
        if nodes is None:
            nodes = self._config.get("market_data", {}).get("nodes", _DEFAULT_NODES)

        total = 0
        for node in nodes:
            try:
                items = self._fetcher.fetch_all(node)
                parsed = parse_node_data(items)
                self._store_node_data(parsed)
                total += len(parsed)
            except Exception as e:
                logger.error("节点 %s 数据加载失败: %s", node, e)
        logger.info("节点数据加载完成: %d 条", total)
        return total

    def load_classifications(self) -> dict:
        """抓取并存储行业和概念分类。返回统计。"""
        stats = {"industries": 0, "concepts": 0, "mappings": 0}

        # 加载申万行业
        stats["industries"] = self._load_sw_industries()

        # 加载概念板块
        stats["concepts"] = self._load_concepts()

        # 加载分类映射
        stats["mappings"] = self._load_symbol_classifications()

        logger.info("分类加载完成: %d 行业, %d 概念, %d 映射",
                     stats["industries"], stats["concepts"], stats["mappings"])
        return stats

    def load_all(self) -> dict:
        """加载节点数据 + 分类。"""
        node_count = self.load_node_data()
        cls_stats = self.load_classifications()
        cls_stats["node_data"] = node_count
        return cls_stats

    def _store_node_data(self, items: list[dict]) -> None:
        """存储节点数据到 dwd_node_data（INSERT OR REPLACE）。"""
        now = datetime.now().isoformat()
        rows = []
        for item in items:
            rows.append((
                item["symbol"], item["code"], item["name"],
                item["trade"], item["pricechange"], item["changepercent"],
                item["buy"], item["sell"], item["settlement"],
                item["open"], item["high"], item["low"],
                item["volume"], item["amount"], item["ticktime"],
                item["per"], item["pb"], item["mktcap"], item["nmc"],
                item["turnoverratio"], now,
            ))
        self._conn.executemany("""
            INSERT OR REPLACE INTO dwd_node_data
            (symbol, code, name, trade, pricechange, changepercent,
             buy, sell, settlement, open, high, low, volume, amount,
             ticktime, per, pb, mktcap, nmc, turnoverratio, fetched_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, rows)
        self._conn.commit()

    def _load_sw_industries(self) -> int:
        """加载申万行业分类节点树并存入 dim_industries。"""
        try:
            tree = self._fetch_nodes_tree()
        except Exception as e:
            logger.error("获取节点树失败: %s", e)
            return 0

        count = 0
        # 从树中提取申万行业节点
        for node_code in _SW_NODES:
            try:
                items = self._fetcher.fetch_all(node_code, num=1)
                if items:
                    # 用节点代码的后两位或名称匹配行业
                    name = node_code  # 默认
                    # 从节点代码提取简短名称
                    level = 1
                    self._conn.execute("""
                        INSERT OR REPLACE INTO dim_industries
                        (code, name, level, parent_code, updated_at)
                        VALUES (?, ?, ?, ?, ?)
                    """, (node_code, name, level, None, datetime.now().isoformat()))
                    count += 1
            except Exception:
                pass

        self._conn.commit()
        return count

    def _load_concepts(self) -> int:
        """加载概念板块数据。"""
        # 概念板块数量太多（900+），只加载 gn_ 前缀的热门概念
        concept_nodes = self._config.get("market_data", {}).get("concept_nodes", [])
        if not concept_nodes:
            return 0

        count = 0
        for node_code in concept_nodes:
            try:
                items = self._fetcher.fetch_node(node_code, num=1)
                if items:
                    self._conn.execute("""
                        INSERT OR REPLACE INTO dim_concepts
                        (code, name, updated_at)
                        VALUES (?, ?, ?)
                    """, (node_code, node_code, datetime.now().isoformat()))
                    count += 1
            except Exception:
                pass

        self._conn.commit()
        return count

    def _load_symbol_classifications(self) -> int:
        """为当前配置的 symbols 加载行业和概念分类映射。"""
        symbols = self._config.get("symbols", [])
        if not symbols:
            return 0

        count = 0
        for sym in symbols:
            # 查询该 symbol 属于哪些行业节点
            try:
                self._load_symbol_industry(sym)
                count += 1
            except Exception as e:
                logger.debug("获取 %s 分类失败: %s", sym, e)

        self._conn.commit()
        return count

    def _load_symbol_industry(self, symbol: str) -> None:
        """通过 getHQNodes 树查找 symbol 的行业归属。"""
        # 简化实现：通过遍历行业节点查找
        for node_code in _SW_NODES:
            try:
                items = self._fetcher.fetch_node(node_code, num=80, page=1)
                symbols_in_node = {item.get("symbol") for item in items}
                if symbol in symbols_in_node:
                    self._conn.execute("""
                        INSERT OR REPLACE INTO dim_symbol_classifications
                        (symbol, classification_type, classification_code, updated_at)
                        VALUES (?, ?, ?, ?)
                    """, (symbol, "sw_industry", node_code,
                          datetime.now().isoformat()))
                    return  # 找到即返回
            except Exception:
                pass

    def _fetch_nodes_tree(self) -> list:
        """获取节点树结构。"""
        resp = requests.get(
            _NODES_URL,
            headers={"Referer": "https://vip.stock.finance.sina.com.cn/"},
            timeout=self._timeout,
        )
        resp.raise_for_status()
        return resp.json()

    @property
    def _timeout(self) -> int:
        return self._config.get("http", {}).get("timeout", 10)

    def close(self) -> None:
        self._fetcher.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
