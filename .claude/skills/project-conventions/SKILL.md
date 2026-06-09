---
name: project-conventions
description: sina-hq-crawler 项目架构约定与编码规范
user-invocable: false
---

# 项目约定

sina-hq-crawler 项目的架构约定与编码规范。Claude 在修改本项目代码时应遵循以下约定。

## 数据仓库分层架构

| 层 | 表名 | 职责 | 特点 |
|----|------|------|------|
| ODS | `ods_raw_quotes` | 原始数据日志 | 每次 API 响应都插入，保留原始 JSON |
| DWD | `dwd_quotes` | 去重清洗后的 tick | 仅当数据变化时插入（四字段比较） |
| DWS | `dws_minute_bars` | 分钟K线聚合 | `INSERT OR REPLACE`，WITHOUT ROWID |
| ADS | 视图 | 应用层查询 | `ads_latest_quotes`, `ads_intraday_stats`, `ads_price_alerts` |

## DWD 去重规则

只有当以下四个字段中任意一个与上一条记录不同时才插入：
- `current_price`
- `volume`
- `high`
- `low`

`None` 值不参与比较。去重逻辑在 `storage.py` 的 `_should_insert()` 中实现。

## 线程模型

- HTTP 请求可以并发（线程池）
- 数据库写入必须在主线程
- 符号数 < `auto_threshold`(6) → 单线程
- 符号数 >= 6 → `min(ceil(n/batch_size), max_workers)` 线程

## 编码约定

- API 响应编码：GB2312 → UTF-8
- 浮点数解析：空串/零/"N/A" → `None`（使用 `parser._float()`）
- 时间戳：Unix timestamp（秒），毫秒精度用 `ts_ms`
- 配置访问：嵌套字典 `config['crawl']['poll_interval']`

## 数据库约定

- SQLite WAL 模式
- `synchronous = NORMAL`
- `busy_timeout = 5000ms`
- 批量提交：每 N 条或每 M 秒
- `WITHOUT ROWID` 用于高频更新的表（`dws_minute_bars`, `dws_daily_summary`）

## 命名约定

- 模块名：小写下划线（`fetcher.py`, `storage.py`）
- 类名：大驼峰（`QuoteFetcher`, `QuoteStorage`）
- 私有方法：下划线前缀（`_should_insert`, `_build_dwd_row`）
- 常量：大写下划线（`_DEFAULTS`）

## 日志约定

- 使用 `logging.getLogger(__name__)`
- 告警使用 `monitor._alert(level, message)`
- 日志轮转：10MB，保留 5 份
- 告警级别：INFO / WARNING / CRITICAL

## 测试约定

- 测试文件 1:1 对应源文件
- 使用 `conftest.py` 共享 fixtures
- Mock 外部依赖（HTTP、磁盘 I/O）
- 覆盖率目标：90%+
