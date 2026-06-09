# 守护进程设计文档

**日期**: 2026-06-09
**状态**: 已批准
**方案**: C — Scheduler 扩展 + daemon 壳

## 概述

为 sina-hq-crawler 新增守护进程能力，支持时间窗口调度、配置热加载、自动重启自愈、健康检查 HTTP 接口和盘后自动报告。

当前系统是 `uv run crawl` 一次性启动、手动停止的模式。守护进程将其升级为：长期运行、按交易时段自动开关采集、自动维护的完整服务。

## 配置结构

在 `config.yaml` 新增 `sessions` 和 `daemon` 配置块：

```yaml
# 交易时间段（混合模式：全局默认 + symbol 级覆盖）
sessions:
  default:
    - start: "09:30"
      end: "11:30"
    - start: "13:00"
      end: "15:00"
  overrides:
    sh000001:
      - start: "09:15"
        end: "15:15"

# 守护进程
daemon:
  pid_file: "logs/crawler.pid"
  health:
    enabled: true
    host: "127.0.0.1"
    port: 8089
  hot_reload:
    enabled: true
    watch_file: "config.yaml"
  post_market_report:
    enabled: true
    output_dir: "reports/"
    auto_cleanup: true
  auto_restart:
    enabled: true
    max_retries: 5
    retry_delay: 10
```

### _DEFAULTS 新增项

```python
"daemon": {
    "pid_file": "logs/crawler.pid",
    "health": {"enabled": True, "host": "127.0.0.1", "port": 8089},
    "hot_reload": {"enabled": True, "watch_file": "config.yaml"},
    "post_market_report": {"enabled": True, "output_dir": "reports/", "auto_cleanup": True},
    "auto_restart": {"enabled": True, "max_retries": 5, "retry_delay": 10},
},
"sessions": {
    "default": [
        {"start": "09:30", "end": "11:30"},
        {"start": "13:00", "end": "15:00"},
    ],
    "overrides": {},
},
```

## 模块结构

### 新增模块

| 模块 | 职责 |
|------|------|
| `src/daemon.py` | 守护进程主入口：PID 管理、信号处理（SIGTERM/SIGINT/SIGHUP）、主循环、协调各子系统 |
| `src/session.py` | 时间窗口引擎：`is_in_session()`、`get_active_symbols()`、`calc_next_start()`、`sleep_until()` |
| `src/health.py` | HTTP 健康检查：`threading.Thread` + `http.server.HTTPServer`，127.0.0.1 返回 JSON |
| `src/reloader.py` | 配置热加载：mtime 比对 + validate，失败回滚保留旧配置 |
| `src/reporter.py` | 盘后报告：调用 `analyze.generate_report()`，可选触发 `maintenance.run_retention_cleanup()` |

### 修改模块

| 模块 | 变更 |
|------|------|
| `src/scheduler.py` | 增加 `stop()` 方法（外部可控停止）、`is_running` 属性 |
| `src/crawler.py` | 新增 `daemon` 子命令分发（`start/stop/status/reload`） |
| `src/config.py` | `_DEFAULTS` 新增 `daemon` 和 `sessions` 键，`_validate()` 增加时间段格式校验 |

### CLI 入口

```bash
uv run daemon start              # 启动守护进程（前台运行）
uv run daemon start --detach     # 后台运行（fork + PID 文件）
uv run daemon stop               # 读取 PID 文件，发送 SIGTERM
uv run daemon status             # 调用 /healthz 或读取状态文件
uv run daemon reload             # 发送 SIGHUP 触发热加载
```

在 `pyproject.toml` 的 `[project.scripts]` 中新增：
```toml
daemon = "src.daemon:main"
```

## daemon 主循环

```python
def main_loop(self):
    while not self._shutdown:
        config = self.get_config()  # 可能被热更新
        session_info = get_current_session(config)

        if session_info is None:
            # 不在交易时段，休眠至下一窗口
            next_start = calc_next_start(config)
            self.logger.info("休眠至 %s", next_start)
            self._interruptible_sleep(next_start)
            continue

        # 在交易时段内
        symbols = session_info.symbols
        self.logger.info("进入交易时段 %s-%s, 采集 %s",
                         session_info.start, session_info.end, symbols)

        scheduler = CrawlScheduler(config, storage, fetcher, parser, monitor)
        scheduler.run(symbols=symbols, end_time=session_info.end_dt)
        # run() 内部会在 end_time 到达时自动退出

        # 时段结束
        if config['daemon']['post_market_report']['enabled']:
            generate_report(config)

        # 等待下一窗口或次日
        next_start = calc_next_start(config)
        if next_start:
            self._interruptible_sleep(next_start)
        else:
            self.logger.info("今日交易结束，等待明日")
            self._sleep_until_tomorrow(config)
```

### Scheduler 修改

在 `CrawlScheduler.run()` 增加 `end_time` 参数：

```python
def run(self, symbols=None, end_time=None):
    """主循环。新增参数:
    - symbols: 覆盖 self._symbols（daemon 传入当前时段的 symbols）
    - end_time: datetime，到达时自动退出（替代 test_duration）
    """
```

判断逻辑：每次循环检查 `datetime.now() >= end_time`，是则设 `_shutdown = True`。与现有 `test_duration` 逻辑兼容：两者取先到者。

## 时间窗口引擎 (session.py)

### 核心类

```python
@dataclass
class SessionWindow:
    start: time        # 开始时间
    end: time          # 结束时间
    symbols: list[str] # 本窗口采集的 symbols

class SessionManager:
    def __init__(self, config: dict):
        self._sessions = self._parse_sessions(config)

    def get_current_session(self) -> SessionWindow | None:
        """返回当前应采集的窗口，不在任何窗口内返回 None"""

    def get_active_symbols(self, window: SessionWindow) -> list[str]:
        """返回当前窗口应采集的 symbols（合并 default + overrides）"""

    def calc_next_start(self) -> datetime | None:
        """计算下一个窗口的开始时间，今日无更多窗口返回 None"""

    def sleep_until(self, target: datetime, interrupt_check: Callable) -> None:
        """可中断的休眠，每秒检查 interrupt_check()"""
```

### 时间段合并规则

- `sessions.default` 定义全局时段，应用于所有 symbols
- `sessions.overrides.<symbol>` 覆盖该 symbol 的时段
- 不在 overrides 中的 symbol 使用 default
- 一个 symbol 可配置多个不连续时段

### 边界处理

- 当前时间恰好等于 start → 进入窗口
- 当前时间恰好等于 end → 已过窗口
- 窗口跨越午夜（如 23:00-01:00）→ 支持（end < start 视为跨日）
- 非交易日（周末/节假日）→ v1 不处理，按时间照常检查；未来可扩展交易日历

## 健康检查 (health.py)

### 实现

- `threading.Thread` 运行 `http.server.HTTPServer`
- 仅监听 `127.0.0.1`，不暴露外部
- 端口被占用时回退到状态文件模式（`logs/health.json`）

### 端点

**GET /healthz** → 200 JSON:
```json
{
  "status": "running",
  "uptime_seconds": 12345,
  "current_session": {
    "start": "09:30",
    "end": "11:30",
    "remaining_seconds": 3600
  },
  "symbols": ["sh000001", "bj920576"],
  "last_fetch_time": "2026-06-09T10:15:30",
  "stats": {
    "rounds": 100,
    "success": 98,
    "failures": 2,
    "ticks_stored": 150
  },
  "config_version": 3
}
```

**GET /healthz** (不在交易时段) → 200 JSON:
```json
{
  "status": "sleeping",
  "next_session_start": "13:00",
  "sleep_remaining_seconds": 1800
}
```

## 配置热加载 (reloader.py)

### 机制

- 每 5 秒检查 `config.yaml` 的 mtime
- 收到 SIGHUP 时立即检查
- 变化时：`load_config()` → `_validate()` → 成功则替换，失败则保留旧配置并 CRITICAL 告警
- 生效时机：**下一个时间窗口开始时**生效，不中断当前采集
- 递增 `config_version` 计数器供健康检查展示

### 可热更新项

| 配置项 | 支持热更新 | 说明 |
|--------|-----------|------|
| symbols | ✅ | 下一窗口生效 |
| sessions | ✅ | 影响窗口调度 |
| crawl.poll_interval | ✅ | 下一窗口生效 |
| http.timeout | ✅ | 下一窗口生效 |
| logging.level | ✅ | 立即生效 |
| monitor.* | ✅ | 下一窗口生效 |
| database.path | ❌ | 需重启 |
| daemon.* | ❌ | 需重启 |

## 盘后自动报告 (reporter.py)

### 触发时机

每个交易窗口结束后自动执行。

### 流程

1. 调用 `analyze.generate_report(conn, config, date, symbols)` 生成当日报告
2. 写入 `reports/YYYY-MM-DD_session_<start>_<end>.md`
3. 如果 `auto_cleanup` 为 true，调用 `maintenance.run_retention_cleanup(conn, config)`
4. 记录日志

## 错误处理与自愈

### 自动重启

```
采集循环异常退出
  → 捕获异常，记录 CRITICAL 日志
  → 检查当日重启计数 < max_retries
  → sleep(retry_delay) 秒
  → 重新创建 scheduler 并 run()
  → 重启计数 +1
```

### 错误场景处理

| 场景 | 处理方式 |
|------|----------|
| 采集循环异常退出 | auto_restart 重启，间隔 retry_delay 秒，单日不超过 max_retries 次 |
| 配置文件损坏 | 保留旧配置运行，日志 CRITICAL 告警 |
| HTTP 健康端口被占用 | 回退到状态文件模式（`logs/health.json`），日志 WARNING |
| 数据库锁定 | 现有 busy_timeout 机制处理，daemon 层不额外干预 |
| 当日重启次数超限 | 停止采集，日志 CRITICAL，等待次日重置计数器 |

### 重启计数器

- 按日期重置（每日 00:00 清零）
- 存储在内存中，不持久化（daemon 重启后重新计数）

## 测试策略

| 测试文件 | 覆盖内容 |
|----------|----------|
| `tests/test_session.py` | 时间窗口判断、跨日边界、多窗口切换、symbol 合并规则、overrides 优先级 |
| `tests/test_daemon.py` | PID 文件生命周期、信号处理、主循环状态机、自愈重启计数 |
| `tests/test_health.py` | HTTP 端点 JSON 响应、端口占用回退、状态文件写入 |
| `tests/test_reloader.py` | mtime 变更检测、配置验证失败回滚、config_version 递增 |
| `tests/test_reporter.py` | 报告生成触发、maintain 调用、输出目录创建 |

所有测试使用 mock 时间（`freezegun` 或 `unittest.mock.patch`）以避免依赖真实时钟。

## 文件清单

### 新增文件

```
src/daemon.py       # 守护进程主入口 + CLI
src/session.py      # 时间窗口引擎
src/health.py       # HTTP 健康检查
src/reloader.py     # 配置热加载
src/reporter.py     # 盘后报告
tests/test_session.py
tests/test_daemon.py
tests/test_health.py
tests/test_reloader.py
tests/test_reporter.py
docs/superpowers/specs/2026-06-09-daemon-design.md  # 本文档
```

### 修改文件

```
src/scheduler.py    # 增加 stop()、end_time 支持
src/crawler.py      # 新增 daemon 子命令分发
src/config.py       # _DEFAULTS 新增 daemon/sessions
config.yaml         # 新增 sessions/daemon 配置
config.example.yaml # 同步更新示例
pyproject.toml      # 新增 daemon 入口
CLAUDE.md           # 更新命令列表
```
