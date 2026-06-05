# 新浪行情采集系统 — 测试方案

## 测试目标

确保所有模块测试覆盖率 > 90%，重点覆盖分支逻辑、边界条件、异常处理。

## 测试矩阵

| 模块 | 测试文件 | 测试项数 | 覆盖重点 |
|------|----------|---------|----------|
| config.py | test_config.py | 12 | 深度合并、校验、默认值、文件加载 |
| db.py | test_db.py | 8 | 建表、索引、视图、WAL、幂等性 |
| parser.py | test_parser.py | 15 | _float边界、指数/个股解析、order_book、无效输入 |
| fetcher.py | test_fetcher.py | 10 | 成功/失败、重试退避、上下文管理器、HTTP错误 |
| storage.py | test_storage.py | 18 | 去重、批量提交、DWS更新、finalize、监控集成 |
| monitor.py | test_monitor.py | 12 | 延迟告警、价格异常、断流检测、连续失败、禁用模式 |
| logger.py | test_logger.py | 5 | handler配置、轮转、级别、目录创建 |
| scheduler.py | test_scheduler.py | 10 | 并发决策、信号处理、单线程/多线程、清理 |
| maintenance.py | test_maintenance.py | 8 | 归档、清理、VACUUM、dry-run |
| analyze.py | test_analyze.py | 10 | SQL聚合、报告生成、无数据、日期过滤 |
| crawler.py | test_crawler.py | 6 | CLI参数、组件组装、dry-run |

## 测试策略

### Mock 策略
- **SQLite**: 使用 `:memory:` 数据库，无需 mock
- **requests**: 使用 `unittest.mock.patch` mock `Session.get`
- **time/datetime**: 使用 `unittest.mock.patch` 控制时间
- **signal**: 测试 scheduler 时 mock `signal.signal`
- **文件系统**: 使用 `tmp_path` fixture 创建临时文件

### 测试数据
- 上证指数: `var hq_str_sh000001="上证指数,4044.8292,4057.7811,4042.6525,..."`
- 天力复合: `var hq_str_bj920576="天力复合,58.390,56.840,69.690,..."`
- 无效数据: 空行、格式错误、字段不足

### 运行方式
```bash
uv run pytest tests/ -v --tb=short
uv run pytest tests/ --cov=src --cov-report=term-missing
```

## 已知风险

1. `analyze_symbol` 的 ODS 查询使用 `LIKE '%symbol%'` 可能误匹配
2. `_float` 将 0.0 视为 None — 这是有意设计，测试需验证
3. `storage._build_dwd_row` 中 `order_book` 字段的索引位置需要确认
