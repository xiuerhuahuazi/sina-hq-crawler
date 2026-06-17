# Changelog

## [Unreleased]

### Fixed
- **P0**: 去重率/数据完整度计算错误 — ODS/DWD 现在按日期过滤，不再跨全量历史数据计算
- **P0**: 去重率异常时标记为告警（之前错误地标记为"数据活跃"）
- **P1**: 多智能体分析系统 — MarketAnalyst 放宽指标门槛（仅需1个有效指标），支持 MA5/VWAP/量比
- **P1**: Synthesizer 报告增加数据状态显示（技术指标/基本面数据可用性）
- **P2**: Monitor 告警泛滥 — 仅对实际存储的标的做 gap 检测，`gap_threshold_seconds` 15s→60s
- **P3**: DWD 数据累积 — `dwd_days` 90→14，新增 `idx_dwd_quote_date` 索引加速清理
