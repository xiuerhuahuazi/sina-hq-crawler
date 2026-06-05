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
| `src/crawler.py` | CLI 入口（`--config`、`--symbols`、`--duration`、`--dry-run`） |
| `src/analyze.py` | 分析报告（SQL 聚合、动态生成 Markdown） |

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
