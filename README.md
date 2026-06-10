# sina-hq-crawler

基于新浪财经 `hq.sinajs.cn` 接口的 A 股实盘数据采集系统，采用数据仓库 ODS → DWD → DWS → ADS 四层架构。

## 快速开始

```bash
# 安装依赖
uv sync

# 验证配置
uv run crawl --dry-run

# 启动采集（读取 config.yaml）
uv run crawl

# 指定标的和时长
uv run crawl --symbols sh000001 bj920576 --duration 300

# 分析数据
uv run analyze
uv run analyze --date 2026-06-05 --output report.md

# 数据维护
uv run maintain --dry-run    # 预览清理
uv run maintain              # 执行清理 + 归档
```

## 守护进程

守护进程按交易时段自动调度采集，无需手动启动/停止。

```bash
uv run daemon start              # 前台运行（自动按时段采集/休眠）
uv run daemon start --detach     # 后台运行
uv run daemon stop               # 停止守护进程
uv run daemon status             # 查看运行状态
uv run daemon reload             # 热加载配置（SIGHUP）
```

### 时间窗口调度

在 `config.yaml` 的 `sessions` 中配置交易时段：

```yaml
sessions:
  default:                        # 全局默认时段
    - start: "09:30"
      end: "11:30"
    - start: "13:00"
      end: "15:00"
  overrides:                      # 个别 symbol 可覆盖
    sh000001:
      - start: "09:15"
        end: "15:15"
```

- 全局 `default` 时段应用于所有未 override 的标的
- `overrides` 中的标的使用独立时段
- 窗口外自动休眠，窗口内自动启动采集
- 支持跨日窗口（如 23:00-01:00）

### 守护进程能力

| 能力 | 说明 |
|------|------|
| 时间窗口调度 | 按配置时段自动开关采集，窗口外休眠等待 |
| 配置热加载 | 修改 config.yaml 后 `uv run daemon reload` 或自动检测 mtime 变化，下一窗口生效 |
| 自动重启自愈 | 采集异常自动重启，单日不超过 `max_retries` 次 |
| 盘后自动报告 | 每个交易窗口结束后自动生成分析报告 |
| 健康检查 HTTP | `127.0.0.1:8089/healthz` 返回 JSON 状态，端口被占用时回退文件模式 |

## 架构

### 数据仓库四层

| 层 | 表名 | 职责 |
|----|------|------|
| ODS | `ods_raw_quotes` | 原始 API 响应日志（只追加） |
| DWD | `dwd_quotes` | 去重后的 tick 数据 + 计算字段 |
| DWS | `dws_minute_bars` / `dws_daily_summary` | 分钟 K 线 + 日终汇总 |
| ADS | 视图 | `ads_latest_quotes` / `ads_intraday_stats` / `ads_price_alerts` |

### 模块分工

| 模块 | 职责 |
|------|------|
| `src/config.py` | YAML 配置加载 + 默认值合并 + 校验 |
| `src/db.py` | SQLite 初始化（WAL、四层建表、视图） |
| `src/fetcher.py` | HTTP 请求（Session 复用、指数退避重试） |
| `src/parser.py` | 原始响应解析（纯函数、含买卖五档提取） |
| `src/storage.py` | ODS/DWD/DWS 写入（去重、批量提交） |
| `src/scheduler.py` | 轮询调度（可选线程池、信号处理、优雅关闭） |
| `src/logger.py` | 日志系统（RotatingFileHandler 轮转） |
| `src/monitor.py` | 监控告警（延迟/断流/价格异常/连续失败） |
| `src/maintenance.py` | 数据维护（过期清理 + ODS gzip 归档 + VACUUM） |
| `src/crawler.py` | 采集 CLI 入口（`--config`、`--symbols`、`--duration`、`--dry-run`） |
| `src/analyze.py` | 分析报告（SQL 聚合、动态生成 Markdown） |
| `src/daemon.py` | 守护进程主入口（PID 管理、信号处理、主循环、CLI） |
| `src/session.py` | 时间窗口引擎（时段判断、symbol 合并、休眠调度） |
| `src/health.py` | HTTP 健康检查（127.0.0.1 本地监听） |
| `src/reloader.py` | 配置热加载（mtime 检测 + SIGHUP 触发） |
| `src/reporter.py` | 盘后自动报告（调用 analyze + 可选 maintain） |
| `src/indicators.py` | 技术指标计算（盘中实时 + 离线历史，14 种指标） |

### 并发自动扩缩

```
concurrency.enabled = auto（默认）
  标的数 < 6 → 单线程
  标的数 >= 6 → min(ceil(n/4), 4) 线程
```

线程池只做 HTTP 请求，结果入 Queue，主线程串行写 DB。

### DWD 去重规则

仅当 `current` / `volume` / `high` / `low` 中任一与同一 symbol 最新 DWD 行不同时才写入。
全部相同则跳过（ODS 照写，保证原始数据完整）。

## 核心 API

```
GET https://hq.sinajs.cn/rn={timestamp}&list={symbol_list}
Header: Referer: https://finance.sina.com.cn/
```

- 编码：GB2312（需转 UTF-8）
- 代码前缀：sh=上交所、sz=深交所、bj=北交所
- 批量查询：`list=sh000001,bj920576,sz399001`

### 更新机制（来自 stock_A.js）

- **首选**: WebPush4 (Flash Socket 实时推送, 3秒间隔) — 已过时
- **降级**: JSONP 轮询, 每 3 秒一次
- **本方案**: 直接 HTTP 轮询 `hq.sinajs.cn`, 间隔 3 秒

## 参考文件

| 文件 | 大小 | 用途 |
|------|------|------|
| stock_A.js | 144KB | 上证指数页主逻辑：行情请求、数据解析 |
| utils-hq.js | 35KB | 行情工具函数：格式化、时钟 |
| IO.WebPush4.js | 40KB | Flash Socket 推送库（已过时） |

## 配置

编辑 `config.yaml`，参考 `config.example.yaml` 中的注释说明。

## 技术指标

`src/indicators.py` 提供盘中实时和离线历史两类指标计算。

### 盘中实时指标

基于当前 session 的分钟K线和 tick 数据，交易时段内实时可用：

| 指标 | 函数 | 说明 |
|------|------|------|
| VWAP | `intraday_vwap()` | 成交量加权平均价，机构基准价 |
| 量比 | `intraday_volume_ratio()` | 最新分钟量 / 前 N 分钟均量 |
| 买卖价差 | `intraday_orderbook_spread()` | ask[0] - bid[0]，流动性指标 |
| 盘口挂单比 | `intraday_orderbook_imbalance()` | bid 总量 / ask 总量 |
| 累计成交量 | `intraday_cumulative_volume()` | 当日成交总量 |

### 离线历史指标

基于 `dws_daily_summary` 多日数据，随运行天数积累：

| 指标 | 函数 | 最少天数 |
|------|------|---------|
| MA/EMA | `daily_ma()` / `daily_ema()` | N 天 |
| MACD(12,26,9) | `daily_macd()` | 26 天 |
| RSI(14) | `daily_rsi()` | 15 天 |
| BOLL(20) | `daily_boll()` | 20 天 |
| ATR(14) | `daily_atr()` | 15 天 |
| OBV | `daily_obv()` | 2 天 |
| KDJ(9) | `daily_kdj()` | 9 天 |

### 一键计算

```python
from src.indicators import compute_latest
latest = compute_latest(conn, "sh000001")
# {'vwap': 3200.5, 'rsi14': 65.3, 'macd_dif': 12.5, ...}
```

## 数据能力评估

详见 [docs/data-capability-assessment.md](docs/data-capability-assessment.md)：
- 当前数据字段清单
- 7 项关键缺口（历史日线、复权、成交笔数、资金流向、基本面、行业分类、两融）
- 量化框架适配性（pandas / TA-Lib / backtrader）
- 未来优化路线图
