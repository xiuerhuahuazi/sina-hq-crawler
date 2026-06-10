#!/usr/bin/env python3
"""守护进程 — 时间窗口调度、配置热加载、健康检查、自愈重启。"""

import argparse
import logging
import os
import signal
import sys
import time
from datetime import datetime, date, timedelta
from pathlib import Path

from src.config import load_config
from src.logger import setup_logging
from src.db import init_db
from src.fetcher import QuoteFetcher
from src.parser import parse_response
from src.storage import QuoteStorage
from src.scheduler import CrawlScheduler
from src.monitor import QuoteMonitor
from src.session import SessionManager
from src.reloader import ConfigReloader
from src.health import HealthServer
from src.reporter import PostSessionReporter
from src.market_data import MarketDataLoader

logger = logging.getLogger(__name__)


class CrawlDaemon:
    """守护进程主循环：按交易时段自动开关采集。"""

    def __init__(self, config_path: str | None = None) -> None:
        self._config_path = config_path
        self._config = load_config(config_path)
        self._shutdown = False

        # 子系统（延迟初始化）
        self._reloader: ConfigReloader | None = None
        self._health: HealthServer | None = None
        self._reporter: PostSessionReporter | None = None

        # 自愈计数器
        self._retry_count: int = 0
        self._retry_date: date = date.today()
        self._start_time: float = time.time()

    def run(self) -> None:
        """前台运行守护进程。"""
        setup_logging(self._config)
        self._setup_signals()
        self._write_pid()
        self._init_subsystems()
        self._main_loop()
        self._shutdown_all()

    def run_detach(self) -> None:
        """fork 后台运行。"""
        # 第一次 fork
        pid = os.fork()
        if pid > 0:
            print(f"守护进程已启动 (PID: {pid})")
            sys.exit(0)

        os.setsid()

        # 第二次 fork
        pid = os.fork()
        if pid > 0:
            sys.exit(0)

        # 重定向标准流
        devnull = os.open(os.devnull, os.O_RDWR)
        os.dup2(devnull, 0)
        os.dup2(devnull, 1)
        os.dup2(devnull, 2)
        os.close(devnull)

        self.run()

    def _setup_signals(self) -> None:
        """注册信号处理器（daemon 层统一管理）。"""
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)
        if hasattr(signal, "SIGHUP"):
            signal.signal(signal.SIGHUP, self._handle_hup)

    def _handle_signal(self, signum, frame) -> None:
        logger.info("收到信号 %d，优雅退出", signum)
        self._shutdown = True

    def _handle_hup(self, signum, frame) -> None:
        """SIGHUP 触发热加载。"""
        logger.info("收到 SIGHUP，触发热加载")
        self._try_reload()

    def _write_pid(self) -> None:
        pid_path = Path(self._config["daemon"]["pid_file"])
        pid_path.parent.mkdir(parents=True, exist_ok=True)
        pid_path.write_text(str(os.getpid()), encoding="utf-8")
        logger.debug("PID 文件: %s (%d)", pid_path, os.getpid())

    def _remove_pid(self) -> None:
        pid_path = Path(self._config["daemon"]["pid_file"])
        if pid_path.exists():
            try:
                pid_path.unlink()
            except OSError:
                pass

    def _init_subsystems(self) -> None:
        """初始化热加载、健康检查、报告器。"""
        # 配置热加载
        daemon_cfg = self._config["daemon"]
        if daemon_cfg["hot_reload"]["enabled"]:
            watch = daemon_cfg["hot_reload"]["watch_file"]
            cfg_path = Path(self._config_path) if self._config_path else Path(watch)
            self._reloader = ConfigReloader(cfg_path)

        # 健康检查
        if daemon_cfg["health"]["enabled"]:
            self._health = HealthServer(
                daemon_cfg["health"]["host"],
                daemon_cfg["health"]["port"],
            )
            self._health.start()

        # 报告器（延迟：需要 DB 连接）

    def _main_loop(self) -> None:
        """主循环：检查时段 → 采集/休眠 → 报告 → 等待下一窗口。"""
        db_path = self._config["database"]["path"]
        conn = init_db(db_path, self._config)
        monitor = QuoteMonitor(self._config) if self._config["monitor"]["enabled"] else None
        self._reporter = PostSessionReporter(self._config, conn)

        try:
            while not self._shutdown:
                # 自愈检查：日期变更重置计数器
                today = date.today()
                if today != self._retry_date:
                    self._retry_count = 0
                    self._retry_date = today

                try:
                    self._run_session_loop(conn, monitor)
                except Exception as e:
                    logger.critical("采集循环异常: %s", e)
                    max_retries = self._config["daemon"]["auto_restart"]["max_retries"]
                    retry_delay = self._config["daemon"]["auto_restart"]["retry_delay"]

                    self._retry_count += 1
                    if self._retry_count > max_retries:
                        logger.critical("当日重启次数超限 (%d/%d)，停止采集",
                                        self._retry_count - 1, max_retries)
                        break

                    logger.critical("将在 %ds 后重启 (%d/%d)",
                                    retry_delay, self._retry_count, max_retries)
                    self._interruptible_sleep(retry_delay)
        finally:
            conn.close()

    def _run_session_loop(self, conn, monitor) -> None:
        """单次完整时段循环（可被异常中断后重启）。"""
        config = self._config
        session_mgr = SessionManager(config)

        while not self._shutdown:
            # 检查热加载
            self._try_reload()
            if self._reloader:
                session_mgr = SessionManager(self._config)
                config = self._config

            session = session_mgr.get_current_session()
            self._update_health_status(session_mgr, session)

            if session is None:
                # 不在交易时段
                next_start = session_mgr.calc_next_start_or_tomorrow()
                wait_secs = (next_start - datetime.now()).total_seconds()
                if wait_secs > 60:
                    logger.info("休眠至 %s (%.0f分钟)",
                                next_start.strftime("%Y-%m-%d %H:%M"), wait_secs / 60)
                else:
                    logger.info("休眠至 %s", next_start.strftime("%H:%M"))
                session_mgr.sleep_until(next_start, lambda: self._shutdown)
                continue

            # 在交易时段内
            logger.info("进入交易时段 %s-%s, 采集 %s",
                        session.start_str, session.end_str, session.symbols)

            end_dt = self._calc_session_end_dt(session)

            # 加载市场数据（基本面 + 行业分类）
            self._load_market_data(conn, config)

            with QuoteFetcher(config) as fetcher:
                storage = QuoteStorage(conn, config, monitor)
                scheduler = CrawlScheduler(
                    config, storage, fetcher, parse_response, monitor,
                    register_signals=False,
                )
                scheduler.run(symbols=session.symbols, end_time=end_dt)

            # 时段结束 → 报告
            if self._reporter:
                self._reporter.generate(
                    session.symbols, session.start_str, session.end_str,
                )

            # 更新健康状态
            self._update_health_status(session_mgr, None)

            # 等待下一窗口
            next_start = session_mgr.calc_next_start()
            if next_start:
                logger.info("下一交易时段: %s", next_start.strftime("%H:%M"))
                session_mgr.sleep_until(next_start, lambda: self._shutdown)
            else:
                logger.info("今日交易结束，等待明日")
                tomorrow = session_mgr.calc_next_start_or_tomorrow()
                session_mgr.sleep_until(tomorrow, lambda: self._shutdown)

    def _calc_session_end_dt(self, session):
        """计算当前时段的结束 datetime。"""
        now = datetime.now()
        end = now.replace(
            hour=session.end.hour, minute=session.end.minute,
            second=0, microsecond=0,
        )
        # 跨日处理：如果 end < start 且当前在 start 之后，end 是明天
        if session.is_overnight and now.time() >= session.start:
            end += timedelta(days=1)
        return end

    def _try_reload(self) -> None:
        """尝试热加载配置。"""
        if not self._reloader:
            return
        new_config = self._reloader.check_reload()
        if new_config:
            self._config = new_config
            # logging.level 立即生效
            try:
                log_level = self._config["logging"]["level"]
                logging.getLogger().setLevel(log_level)
            except Exception:
                pass

    def _update_health_status(self, session_mgr, session) -> None:
        """更新健康检查状态。"""
        if not self._health:
            return
        now = datetime.now()
        uptime = int(time.time() - self._start_time)

        if session:
            end_dt = self._calc_session_end_dt(session)
            remaining = max(0, int((end_dt - now).total_seconds()))
            status = {
                "status": "running",
                "uptime_seconds": uptime,
                "current_session": {
                    "start": session.start_str,
                    "end": session.end_str,
                    "remaining_seconds": remaining,
                },
                "symbols": session.symbols,
                "config_version": self._reloader.config_version if self._reloader else 1,
            }
        else:
            next_start = session_mgr.calc_next_start()
            remaining = max(0, int((next_start - now).total_seconds())) if next_start else None
            status = {
                "status": "sleeping",
                "uptime_seconds": uptime,
                "next_session_start": next_start.strftime("%H:%M") if next_start else None,
                "sleep_remaining_seconds": remaining,
                "config_version": self._reloader.config_version if self._reloader else 1,
            }

        self._health.update_status(status)

    def _interruptible_sleep(self, seconds: float) -> None:
        """可中断的休眠。"""
        end = time.time() + seconds
        while time.time() < end and not self._shutdown:
            time.sleep(min(1.0, end - time.time()))

    def _load_market_data(self, conn, config) -> None:
        """加载市场数据（节点行情 + 行业分类）。仅在 enabled 时执行。"""
        md_cfg = config.get("market_data", {})
        if not md_cfg.get("enabled", False):
            return
        try:
            with MarketDataLoader(conn, config) as loader:
                result = loader.load_all()
                logger.info("市场数据加载完成: 节点数据 %d 条, %d 行业, %d 概念",
                            result.get("node_data", 0),
                            result.get("industries", 0),
                            result.get("concepts", 0))
        except Exception as e:
            logger.warning("市场数据加载失败（不影响实时采集）: %s", e)

    def _shutdown_all(self) -> None:
        """清理所有子系统。"""
        self._remove_pid()
        if self._health:
            self._health.stop()
        logger.info("守护进程已退出")


# ---------------------------------------------------------------------------
# CLI 命令
# ---------------------------------------------------------------------------

def _read_pid(config: dict) -> int | None:
    """读取 PID 文件。"""
    pid_path = Path(config["daemon"]["pid_file"])
    if not pid_path.exists():
        return None
    try:
        return int(pid_path.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return None


def _pid_is_alive(pid: int) -> bool:
    """检查进程是否存活。"""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _send_signal_to_pid(config: dict, signum: int) -> bool:
    """向 PID 文件中的进程发送信号。"""
    pid = _read_pid(config)
    if pid is None:
        print("守护进程未运行（PID 文件不存在）")
        return False
    if not _pid_is_alive(pid):
        print(f"守护进程未运行（PID {pid} 不存在）")
        return False
    try:
        os.kill(pid, signum)
        return True
    except OSError as e:
        print(f"发送信号失败: {e}")
        return False


def cmd_start(args) -> None:
    """启动守护进程。"""
    daemon = CrawlDaemon(args.config)
    if args.detach:
        daemon.run_detach()
    else:
        daemon.run()


def cmd_stop(args) -> None:
    """停止守护进程。"""
    config = load_config(args.config)
    if _send_signal_to_pid(config, signal.SIGTERM):
        pid = _read_pid(config)
        print(f"已发送停止信号到 PID {pid}")


def cmd_status(args) -> None:
    """查看守护进程状态。"""
    config = load_config(args.config)
    pid = _read_pid(config)
    if pid is None:
        print("守护进程未运行（PID 文件不存在）")
        return
    if not _pid_is_alive(pid):
        print(f"守护进程未运行（PID {pid} 不存在）")
        return

    print(f"守护进程运行中 (PID: {pid})")

    # 尝试读取健康状态文件（文件回退模式）
    health_file = Path("logs/health.json")
    if health_file.exists():
        try:
            import json
            data = json.loads(health_file.read_text(encoding="utf-8"))
            print(f"状态: {data.get('status', 'unknown')}")
            if data.get("current_session"):
                s = data["current_session"]
                print(f"当前时段: {s['start']}-{s['end']} (剩余 {s['remaining_seconds']}s)")
            print(f"配置版本: {data.get('config_version', '?')}")
        except Exception:
            pass


def cmd_reload(args) -> None:
    """触发热加载。"""
    config = load_config(args.config)
    if _send_signal_to_pid(config, signal.SIGHUP):
        pid = _read_pid(config)
        print(f"已发送热加载信号到 PID {pid}")


def main():
    """daemon CLI 入口。"""
    parser = argparse.ArgumentParser(
        description="新浪财经行情采集守护进程",
    )
    parser.add_argument('--config', '-c', default=None, help='配置文件路径')
    sub = parser.add_subparsers(dest='command')

    p_start = sub.add_parser('start', help='启动守护进程')
    p_start.add_argument('--detach', action='store_true', help='后台运行')
    p_start.add_argument('--config', '-c', default=None, help='配置文件路径')

    p_stop = sub.add_parser('stop', help='停止守护进程')
    p_stop.add_argument('--config', '-c', default=None, help='配置文件路径')

    p_status = sub.add_parser('status', help='查看运行状态')
    p_status.add_argument('--config', '-c', default=None, help='配置文件路径')

    p_reload = sub.add_parser('reload', help='热加载配置')
    p_reload.add_argument('--config', '-c', default=None, help='配置文件路径')

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    commands = {
        'start': cmd_start,
        'stop': cmd_stop,
        'status': cmd_status,
        'reload': cmd_reload,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
