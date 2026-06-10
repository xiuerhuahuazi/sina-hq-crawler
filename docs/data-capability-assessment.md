# 数据能力评估与量化指标支持

**日期**: 2026-06-09
**版本**: v1

## 一、当前数据能力

### 已具备的基础

| 数据层 | 可计算的指标类别 | 代表指标 |
|--------|----------------|---------|
| DWS 分钟K线 (OHLCV) | 趋势类 | MA/EMA/MACD/BOLL/DMI |
| DWS 分钟K线 (OHLCV) | 震荡类 | RSI/KDJ/CCI/Williams %R |
| DWD tick (delta_volume) | 量价类 | OBV/VWAP/量比/换手率 |
| DWD tick (high/low) | 波动类 | ATR/历史波动率 |
| order_book (买卖五档) | 微观结构 | 买卖价差/盘口挂单比 |
| dws_daily_summary | 日线级别 | 仅当日，无法计算多日指标 |

### 当前字段清单

**DWD tick 层**:
`symbol`, `name`, `open`, `prev_close`, `current`, `high`, `low`,
`volume`, `amount`, `change_pct`, `delta_volume`, `delta_amount`,
`tick_index`, `order_book`, `fetched_at`, `latency_ms`, `is_first_tick`

**DWS 分钟K线**:
`symbol`, `bar_minute`, `open`, `high`, `low`, `close`,
`volume`, `amount`, `tick_count`

**DWS 日终汇总**:
`symbol`, `trade_date`, `open`, `high`, `low`, `close`, `prev_close`,
`volume`, `amount`, `change_pct`, `tick_count`, `first_tick_at`, `last_tick_at`

**order_book JSON**:
`{"bid": [{"p":价,"v":量}×5], "ask": [{"p":价,"v":量}×5]}`

---

## 二、关键缺口（不做修复，仅记录）

### 缺口 1: 历史日线数据

**现状**: `dws_daily_summary` 仅保留当日（daemon 每个时段结束时 finalize）
**影响**: 无法计算 MA5/MA20/MA250 等多日均线；MACD 需 26 日 EMA
**解决方向**: daemon 盘后保留 daily_summary 不清理（`dws_days: 365` 配置已有，需确保 daemon 不在盘后调用 maintain 清理当日数据）
**备注**: 随运行天数自然积累，3 个月后可算 MACD，1 年后可算 MA250

### 缺口 2: 复权价格

**现状**: 无前复权/后复权价格
**影响**: 分红送股后指标计算失真，长周期均线偏移
**解决方向**: 需接入除权除息数据（新浪有复权接口），新增 `dim_adjustment` 表
**数据源**: `https://finance.sina.com.cn/realstock/company/{symbol}/hfq.html`

### 缺口 3: 成交笔数

**现状**: 无逐笔成交数据，只有累计 volume
**影响**: 无法精确计算主动买卖量、大单占比
**解决方向**: 新浪 API 字段 6/7 对应 buy/sell volume，当前未提取
**近似方案**: `delta_volume` 可作为每分钟成交量的近似

### 缺口 4: 资金流向

**现状**: 无主力/散户资金流向
**影响**: 无法做资金驱动型策略
**解决方向**: 可通过 order_book 快照序列推算大单挂撤单行为
**近似方案**: 配合成交笔数，按金额阈值区分主力/散户

### 缺口 5: 基本面/财务数据

**现状**: 无 PE/PB/ROE/营收/净利润等
**影响**: 无法做多因子策略、价值投资分析
**解决方向**: 需接入其他数据源（东方财富/同花顺/akshare）
**数据源**: akshare (`pip install akshare`) 可免费获取 A 股基本面数据

### 缺口 6: 行业/板块分类

**现状**: 无行业分类、概念板块信息
**影响**: 无法做行业轮动、板块联动分析
**解决方向**: 申万行业分类或同花顺概念板块数据

### 缺口 7: 融资融券数据

**现状**: 无两融余额数据
**影响**: 无法衡量市场杠杆水平
**解决方向**: 上交所/深交所每日公布两融数据，可通过 akshare 获取

---

## 三、盘中实时指标（已实现）

基于当前 session 的分钟K线和 tick 数据，实时计算。

| 指标 | 全称 | 数据源 | 用途 |
|------|------|--------|------|
| VWAP | 成交量加权平均价 | 分钟K线 | 机构基准价，判断多空 |
| 量比 | 当前分钟量 / 5 分钟均量 | 分钟K线 | 异动检测 |
| 买卖价差 | ask[0] - bid[0] | order_book | 流动性衡量 |
| 盘口挂单比 | bid 总量 / ask 总量 | order_book | 多空力量对比 |
| 累计成交量 | SUM(delta_volume) | 分钟K线 | 交易活跃度 |
| 实时涨跌幅 | (current - prev_close) / prev_close | 分钟K线 | 价格变动 |

### 调用方式

```python
from src.db import init_db
from src.indicators import (
    intraday_vwap,
    intraday_volume_ratio,
    intraday_orderbook_spread,
    intraday_orderbook_imbalance,
    intraday_cumulative_volume,
)

conn = init_db("hq_data.db", config)
vwap = intraday_vwap(conn, "sh000001")          # 实时 VWAP
vol_ratio = intraday_volume_ratio(conn, "sh000001")  # 量比
spread = intraday_orderbook_spread(conn, "bj920576") # 买卖价差
imbalance = intraday_orderbook_imbalance(conn, "bj920576")  # 盘口比
cum_vol = intraday_cumulative_volume(conn, "sh000001")  # 累计量
```

---

## 四、离线历史指标（已实现）

基于 `dws_daily_summary` 的多日数据，适合盘后分析和回测。

| 指标 | 全称 | 最少天数 | 用途 |
|------|------|---------|------|
| MA | 简单移动平均 | N 天 | 趋势判断 |
| EMA | 指数移动平均 | N 天 | 趋势判断（权重衰减） |
| MACD | 指数平滑异同移动平均 | 26 天 | 趋势动量 |
| RSI | 相对强弱指标 | 14 天 | 超买超卖 |
| BOLL | 布林带 | 20 天 | 波动率通道 |
| ATR | 平均真实波幅 | 14 天 | 波动率衡量 |
| OBV | 能量潮 | 2 天 | 量价配合 |
| KDJ | 随机指标 | 9 天 | 超买超卖 |

### 调用方式

```python
from src.indicators import (
    daily_ma, daily_ema, daily_macd, daily_rsi,
    daily_boll, daily_atr, daily_obv, daily_kdj,
    compute_indicators,
)

# 单指标
ma5 = daily_ma(conn, "sh000001", 5)       # 5 日均线
rsi14 = daily_rsi(conn, "sh000001", 14)   # 14 日 RSI
macd = daily_macd(conn, "sh000001")       # 标准 MACD(12,26,9)

# 一键计算所有指标（返回最新一行）
latest = compute_indicators(conn, "sh000001")
# {'ma5': 3200.5, 'ma20': 3180.2, 'rsi14': 65.3, 'macd': 12.5, ...}
```

---

## 五、量化框架适配性

当前数据格式（OHLCV 分钟线）兼容：

| 框架 | 适配方式 |
|------|---------|
| pandas DataFrame | `pd.read_sql("SELECT * FROM dws_minute_bars", conn)` |
| TA-Lib | 标准 OHLCV 输入，可直接调用 `talib.SMA(close, 20)` |
| backtrader | 标准数据格式，需转 CSV 或自定义 DataFeed |
| zipline | 需适配 Bundle API |
| vnpy | 标准 K 线格式可对接 |

### pandas 示例

```python
import pandas as pd
from src.db import init_db

conn = init_db("hq_data.db", config)
df = pd.read_sql("""
    SELECT bar_minute, open, high, low, close, volume, amount
    FROM dws_minute_bars
    WHERE symbol = 'sh000001'
    ORDER BY bar_minute
""", conn, parse_dates=["bar_minute"])

# 直接用 TA-Lib 计算
import talib
df['ma20'] = talib.SMA(df['close'], timeperiod=20)
df['rsi14'] = talib.RSI(df['close'], timeperiod=14)
```

---

## 六、未来优化路线图

| 阶段 | 内容 | 依赖 |
|------|------|------|
| Phase 1 ✅ | 盘中实时指标 + 离线历史指标 | 当前数据（已完成） |
| Phase 2 | 积累 30 天历史数据后验证 MACD/RSI 准确性 | 运行 30 个交易日 |
| Phase 3 | 接入复权因子 | 新浪复权接口 |
| Phase 4 | 接入基本面数据 | akshare |
| Phase 5 | 多因子策略框架 | Phase 3 + Phase 4 |
