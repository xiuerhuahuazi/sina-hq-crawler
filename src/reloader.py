"""配置热加载器 — 监听 config 文件变化并安全重新加载。"""

import logging
import pathlib

from src.config import load_config

logger = logging.getLogger(__name__)


class ConfigReloader:
    """监听配置文件 mtime，变化时重新加载并校验。"""

    def __init__(self, config_path: str | pathlib.Path) -> None:
        self._path = pathlib.Path(config_path).resolve()
        self._mtime: float = self._get_mtime()
        self._config_version: int = 1

    @property
    def config_version(self) -> int:
        return self._config_version

    def _get_mtime(self) -> float:
        """获取配置文件 mtime，不存在返回 0。"""
        try:
            return self._path.stat().st_mtime
        except OSError:
            return 0.0

    def check_reload(self) -> dict | None:
        """检查文件是否变化，变化则尝试重新加载。

        Returns:
            新配置 dict，或 None（未变化 / 加载失败）。
        """
        current_mtime = self._get_mtime()
        if current_mtime == self._mtime:
            return None

        # 文件已变化
        logger.info("配置文件变化 (mtime %.0f → %.0f)，尝试重新加载",
                     self._mtime, current_mtime)
        return self._do_reload()

    def force_reload(self) -> dict | None:
        """强制重新加载（SIGHUP 触发），跳过 mtime 检查。"""
        logger.info("强制重新加载配置")
        return self._do_reload()

    def _do_reload(self) -> dict | None:
        """执行实际的配置加载。成功更新状态，失败保留旧配置。"""
        try:
            new_config = load_config(str(self._path))
        except Exception as e:
            logger.critical("配置重新加载失败，保留当前配置: %s", e)
            return None

        self._mtime = self._get_mtime()
        self._config_version += 1
        logger.info("配置重新加载成功 (version=%d)", self._config_version)
        return new_config
