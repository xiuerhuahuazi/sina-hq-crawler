# 守护进程实施计划

**设计文档**: `docs/superpowers/specs/2026-06-09-daemon-design.md`
**基于**: 方案 C — Scheduler 扩展 + daemon 壳

---

## Phase 1: 配置层扩展

**目标**: 让 config 系统支持 `sessions` 和 `daemon` 两个新配置块。

### 1.1 修改 `src/config.py`

- `_DEFAULTS` 新增两个顶层键（设计文档 §配置结构）:
  ```python
  "sessions": {
      "default": [
          {"start": "09:30", "end": "11:30"},
          {"start": "13:00", "end": "15:00"},
      ],
      "overrides": {},
  },
  "daemon": {
      "pid_file": "logs/crawler.pid",
      "health": {"enabled": True, "host": "127.0.0.1", "port": 8089},
      "hot_reload": {"enabled": True, "watch_file": "config.yaml"},
      "post_market_report": {"enabled": True, "output_dir": "reports/", "auto_cleanup": True},
      "auto_restart": {"enabled": True, "max_retries": 5, "retry_delay": 10},
  },
  ```
- `_validate()` 新增校验:
  - `sessions.default` 中每个元素必须有 `start` 和 `end`，格式 `HH:MM`
  - `sessions.overrides` 的 key 必须是 string，value 是同结构的 list
  - `daemon.health.port` 范围 1024-65535
  - `daemon.auto_restart.max_retries` >= 0

### 1.2 更新配置文件

- `config.yaml`: 新增 `sessions` 和 `daemon` 块（按设计文档示例）
- `config.example.yaml`: 同步新增，添加注释说明每个字段

### 1.3 更新 `tests/test_config.py`

- 新增测试: 默认配置包含 sessions/daemon 键
- 新增测试: YAML 覆盖 sessions/daemon 正确合并
- 新增测试: 无效时间段格式 → ValueError
- 新增测试: 无效端口 → ValueError

### 验证

- `uv run pytest tests/test_config.py -v` 全部通过
- `uv run crawl --dry-run` 不报错（sessions/daemon 有默认值，不影响现有功能）

---

## Phase 2: 时间窗口引擎 (session.py)

**目标**: 实现 `SessionManager`，判断当前是否在交易时段、计算下一窗口。

### 2.1 新建 `src/session.py`

核心数据结构（设计文档 §时间窗口引擎）:
```python
@dataclass
class SessionWindow:
    start: time
    end: time
    symbols: list[str]

class SessionManager:
    def __init__(self, config: dict)
    def get_current_session(self, now: datetime | None = None) -> SessionWindow | None
    def get_active_symbols(self) -> list[str]
    def calc_next_start(self, now: datetime | None = None) -> datetime | None
    @staticmethod
    def sleep_until(target: datetime, interrupt_check: Callable[[], bool], interval: float = 1.0) -> None
```

实现要点:
- `_parse_sessions(config)`: 从 config 读取 `sessions.default` 和 `sessions.overrides`，将 `HH:MM` 字符串转为 `time` 对象
- `get_current_session(now)`: 遍历所有窗口（default + 所有 override symbol 各自的窗口），返回第一个 `start <= now.time() < end` 的窗口。对于 override symbol，窗口的 `symbols` 只含该 symbol；对于 default 窗口，symbols 是所有未 override 的 symbol
- 跨日处理: 当 `end < start` 时视为跨日窗口，判断逻辑为 `now.time() >= start or now.time() < end`
- `calc_next_start(now)`: 找今日所有窗口的 start time，返回最近一个 > now 的。今日无则返回 None
- `sleep_until(target, interrupt_check)`: 每秒循环 `time.sleep(interval)` 并检查 `interrupt_check()` 返回 True 则退出

### 2.2 新建 `tests/test_session.py`

测试用例:
- 不在任何窗口内 → `get_current_session()` 返回 None
- 在 default 窗口内 → 返回正确的 SessionWindow，symbols 为无 override 的 symbol
- 在 override 窗口内 → 返回该 symbol 的独立窗口
- 当前时间恰好等于 start → 进入窗口（>= start）
- 当前时间恰好等于 end → 已过窗口（< end 才在窗口内）
- 跨日窗口（如 23:00-01:00）→ 23:30 在窗口内，02:00 不在
- `calc_next_start()` 今日还有窗口 → 返回正确时间
- `calc_next_start()` 今日无更多窗口 → 返回 None
- `sleep_until()` interrupt_check 返回 True 时提前退出
- 空 sessions 配置 → 始终返回 None

### 验证

- `uv run pytest tests/test_session.py -v` 全部通过

---

## Phase 3: Scheduler 扩展

**目标**: 让 `CrawlScheduler.run()` 支持 `end_time` 参数和 `stop()` 外部停止。

### 3.1 修改 `src/scheduler.py`

在 `run()` 方法签名增加参数（设计文档 §Scheduler 修改）:
```python
def run(self, symbols=None, end_time=None):
```

- `symbols`: 如果传入，覆盖 `self._symbols`（daemon 按时段传入）
- `end_time`: `datetime` 对象，主循环每次迭代检查 `datetime.now() >= end_time`，是则设 `_shutdown = True`
- 兼容: `end_time` 和 `test_duration` 取先到者

新增方法:
```python
def stop(self):
    """外部可控停止（daemon 在时段结束时调用）"""
    self._shutdown = True

@property
def is_running(self) -> bool:
    return self._start_time is not None and not self._shutdown
```

修改 `run()` 循环体，在现有 `test_duration` 检查后增加:
```python
if end_time and datetime.now() >= end_time:
    logger.info("End time reached (%s)", end_time)
    break
```

注意: `run()` 开头需要 `from datetime import datetime`。

同时移除 `run()` 中的 `signal.signal()` 调用——信号处理应由 daemon 层统一管理，scheduler 不应抢占信号。将信号注册移到 `__init__` 中可选执行（当 standalone 模式时注册，daemon 模式时不注册）。最简方案：增加一个 `register_signals=True` 构造参数。

### 3.2 更新 `tests/test_scheduler.py`

- 新增测试: `run(end_time=...)` 到达时间后自动退出
- 新增测试: `stop()` 可以从外部停止 scheduler
- 新增测试: `is_running` 属性正确反映状态
- 新增测试: `symbols` 参数覆盖 config 中的 symbols
- 现有测试不破坏

### 验证

- `uv run pytest tests/test_scheduler.py -v` 全部通过
- `uv run crawl --duration 5` 行为不变（向后兼容）

---

## Phase 4: 配置热加载 (reloader.py)

**目标**: 监听 config 文件变化，安全地重新加载配置。

### 4.1 新建 `src/reloader.py`

```python
class ConfigReloader:
    def __init__(self, config_path: str)
    def check_reload(self) -> dict | None    # 返回新配置或 None
    def force_reload(self) -> dict | None     # SIGHUP 触发
    @property
    def config_version(self) -> int
```

实现:
- `__init__`: 记录初始 mtime 和 config_version=1
- `check_reload()`: 比较当前 mtime 与上次记录。变化时调用 `load_config(path)` 加载+校验。成功则更新 mtime、config_version+=1、返回新配置。失败则 log CRITICAL，返回 None（保留旧配置）
- `force_reload()`: 同 check_reload 但跳过 mtime 检查

### 4.2 新建 `tests/test_reloader.py`

- 文件未变 → 返回 None
- 文件 mtime 变化 + 内容合法 → 返回新 config，version+1
- 文件 mtime 变化 + 内容非法 → 返回 None，旧 config 不变
- `force_reload()` 无论 mtime 是否变化都重新加载
- 文件不存在 → 返回 None

### 验证

- `uv run pytest tests/test_reloader.py -v` 全部通过

---

## Phase 5: 健康检查 (health.py)

**目标**: 本地 HTTP 健康检查端点。

### 5.1 新建 `src/health.py`

```python
class HealthServer:
    def __init__(self, host: str, port: int, status_provider: Callable)
    def start(self) -> bool      # 返回是否成功启动
    def stop(self) -> None
    def update_status(self, status: dict) -> None  # 原子更新状态
```

实现:
- `__init__`: 创建 `HTTPServer`，绑定 `(host, port)`
- `start()`: 在 daemon thread 中运行 `server.serve_forever()`。端口被占用 → log WARNING，回退到文件模式
- `stop()`: 调用 `server.shutdown()`
- `_handler`: 内部 `BaseHTTPRequestHandler` 子类，GET /healthz 返回 200 + JSON。其他路径返回 404
- `update_status()`: 线程安全地更新共享状态 dict（用 `threading.Lock`）

回退文件模式: `start()` 失败时，改为每 30 秒写 `logs/health.json`

### 5.2 新建 `tests/test_health.py`

- 正常启动 + GET /healthz → 200 + JSON
- GET /unknown → 404
- 端口被占用 → 回退到文件模式
- `stop()` 后连接被拒绝
- `update_status()` 后 GET 反映新状态

### 验证

- `uv run pytest tests/test_health.py -v` 全部通过

---

## Phase 6: 盘后报告 (reporter.py)

**目标**: 时段结束后自动生成报告和可选清理。

### 6.1 新建 `src/reporter.py`

```python
class PostSessionReporter:
    def __init__(self, config: dict, conn: sqlite3.Connection)
    def generate(self, symbols: list[str], session_start: str, session_end: str) -> str | None
```

实现:
- `generate()`:
  1. 导入 `src.analyze.generate_report`
  2. 调用 `generate_report(conn, config, date.today(), symbols)`
  3. 写入 `reports/YYYY-MM-DD_session_HHMM_HHMM.md`
  4. 如果 `auto_cleanup` 为 True，导入 `src.maintenance.run_retention_cleanup` 并调用
  5. 返回报告文件路径，或 None 如果失败

### 6.2 新建 `tests/test_reporter.py`

- 正常生成 → 文件存在，内容非空
- auto_cleanup=True → maintenance 被调用
- 生成失败 → 返回 None，不抛异常

### 验证

- `uv run pytest tests/test_reporter.py -v` 全部通过

---

## Phase 7: 守护进程主体 (daemon.py)

**目标**: 组装所有组件，实现 daemon 主循环和 CLI。

### 7.1 新建 `src/daemon.py`

#### 类结构

```python
class CrawlDaemon:
    def __init__(self, config_path: str | None = None)
    def run(self)          # 前台运行
    def run_detach(self)   # fork 后台运行
```

#### 主循环（设计文档 §daemon 主循环）

```
while not shutdown:
    config = reloader.check_reload() or current_config
    session = SessionManager(config).get_current_session()

    if session is None:
        next_start = session_mgr.calc_next_start()
        sleep_until(next_start, interrupt_check=is_shutdown)
        continue

    # 进入交易时段
    scheduler = CrawlScheduler(config, storage, fetcher, parser, monitor, register_signals=False)
    scheduler.run(symbols=session.symbols, end_time=session.end_datetime)

    # 时段结束
    reporter.generate(symbols, session.start, session.end)

    # 等下一窗口
    next = session_mgr.calc_next_start()
    if next: sleep_until(next)
    else: sleep_until_tomorrow()
```

#### 自动重启（设计文档 §错误处理与自愈）

在主循环外包裹重启逻辑:
```python
retry_count = 0
retry_date = date.today()

while not shutdown:
    try:
        main_loop()
    except Exception as e:
        today = date.today()
        if today != retry_date:
            retry_count = 0
            retry_date = today
        retry_count += 1
        if retry_count > max_retries:
            logger.critical("当日重启次数超限 (%d)，停止采集", max_retries)
            break
        logger.critical("采集异常: %s，%d秒后重启 (%d/%d)", e, retry_delay, retry_count, max_retries)
        time.sleep(retry_delay)
```

#### PID 管理

```python
def _write_pid(self):
    pid_path = Path(self._config['daemon']['pid_file'])
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(str(os.getpid()))

def _remove_pid(self):
    pid_path = Path(self._config['daemon']['pid_file'])
    if pid_path.exists():
        pid_path.unlink()

def _read_pid(self) -> int | None:
    # 用于 stop/status 命令
```

#### 信号处理

- SIGTERM/SIGINT → 设 `self._shutdown = True`（优雅退出）
- SIGHUP → 调用 `reloader.force_reload()`

#### detach 实现

```python
def run_detach(self):
    if os.fork() > 0:
        sys.exit(0)
    os.setsid()
    if os.fork() > 0:
        sys.exit(0)
    # 重定向 stdin/stdout/stderr 到 /dev/null 或日志文件
    self._write_pid()
    self.run()
```

### 7.2 CLI 入口

```python
def main():
    parser = argparse.ArgumentParser(description="新浪财经采集守护进程")
    sub = parser.add_subparsers(dest='command')

    p_start = sub.add_parser('start')
    p_start.add_argument('--detach', action='store_true')
    p_start.add_argument('--config', '-c')

    sub.add_parser('stop')
    sub.add_parser('status')
    sub.add_parser('reload')

    args = parser.parse_args()

    if args.command == 'start':
        daemon = CrawlDaemon(args.config)
        if args.detach:
            daemon.run_detach()
        else:
            daemon.run()
    elif args.command == 'stop':
        _send_signal_to_pid(SIGTERM)
    elif args.command == 'status':
        _query_health()
    elif args.command == 'reload':
        _send_signal_to_pid(SIGHUP)
```

### 7.3 新建 `tests/test_daemon.py`

- PID 文件写入/读取/删除
- 信号处理: SIGTERM 设置 _shutdown
- 主循环: 不在时段内 → 进入休眠
- 主循环: 在时段内 → 创建 scheduler 并运行
- 自动重启: 异常后重试，计数递增
- 重启超限 → 停止
- 日期变更 → 重启计数清零
- stop 命令 → 发送 SIGTERM
- status 命令 → 读取健康状态

### 验证

- `uv run pytest tests/test_daemon.py -v` 全部通过

---

## Phase 8: CLI 集成与入口

**目标**: 注册 `daemon` 命令入口。

### 8.1 修改 `pyproject.toml`

`[project.scripts]` 新增:
```toml
daemon = "src.daemon:main"
```

### 8.2 更新 `CLAUDE.md`

命令列表新增:
```
uv run daemon start [--detach] [-c config.yaml]  # 启动守护进程
uv run daemon stop                                # 停止守护进程
uv run daemon status                              # 查看运行状态
uv run daemon reload                              # 热加载配置
```

### 验证

- `uv run daemon --help` 显示帮助
- `uv run daemon start --help` 显示 start 子命令帮助

---

## Phase 9: 全量测试与集成验证

**目标**: 确保新旧功能全部正常。

### 9.1 更新 `tests/conftest.py`

- `base_config` fixture 新增 `sessions` 和 `daemon` 默认值

### 9.2 运行全量测试

```bash
uv run pytest tests/ -v --cov=src --cov-report=term-missing
```

目标: 覆盖率 >= 90%，0 failures。

### 9.3 集成验证

```bash
# 1. daemon dry run（当前不在交易时段，应进入休眠）
uv run daemon start --config config.yaml
# 预期: 日志显示"休眠至 XX:XX"

# 2. 在时段内启动（可手动修改 config.yaml 的 sessions 为当前时间附近测试）
# 预期: 进入采集循环

# 3. 热加载测试
# 修改 config.yaml → 观察日志输出"配置已重新加载"

# 4. stop 测试
# 另一个终端: uv run daemon stop
# 预期: 进程优雅退出

# 5. status 测试
# 在运行时: uv run daemon status
# 预期: JSON 输出运行状态
```

---

## 实施顺序与依赖

```
Phase 1 (config)  ← 无依赖，首先实施
    ↓
Phase 2 (session) ← 依赖 Phase 1 的 sessions 配置
    ↓
Phase 3 (scheduler) ← 依赖 Phase 2 的时间概念
    ↓
Phase 4 (reloader) ← 依赖 Phase 1 的 config
Phase 5 (health)   ← 无强依赖，可与 Phase 4 并行
Phase 6 (reporter) ← 依赖现有 analyze/maintenance 模块
    ↓
Phase 7 (daemon)   ← 依赖 Phase 2-6 所有组件
    ↓
Phase 8 (CLI)      ← 依赖 Phase 7
    ↓
Phase 9 (集成)     ← 依赖所有
```

Phase 4/5/6 可以并行实施（互不依赖）。

## 文件变更总结

| 文件 | 操作 | Phase |
|------|------|-------|
| `src/config.py` | 修改 | 1 |
| `config.yaml` | 修改 | 1 |
| `config.example.yaml` | 修改 | 1 |
| `tests/test_config.py` | 修改 | 1 |
| `src/session.py` | **新增** | 2 |
| `tests/test_session.py` | **新增** | 2 |
| `src/scheduler.py` | 修改 | 3 |
| `tests/test_scheduler.py` | 修改 | 3 |
| `src/reloader.py` | **新增** | 4 |
| `tests/test_reloader.py` | **新增** | 4 |
| `src/health.py` | **新增** | 5 |
| `tests/test_health.py` | **新增** | 5 |
| `src/reporter.py` | **新增** | 6 |
| `tests/test_reporter.py` | **新增** | 6 |
| `src/daemon.py` | **新增** | 7 |
| `tests/test_daemon.py` | **新增** | 7 |
| `pyproject.toml` | 修改 | 8 |
| `CLAUDE.md` | 修改 | 8 |
| `tests/conftest.py` | 修改 | 9 |

共 **7 个新文件** + **8 个修改文件** + **5 个新测试文件** + **3 个修改测试文件**。
