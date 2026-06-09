# sina-hq-crawler

A股实时行情采集器 (新浪财经 hq.sinajs.cn)

## 命令

```bash
uv sync                          # 安装依赖
uv run crawl --dry-run            # 验证配置
uv run crawl                      # 启动采集
uv run crawl --symbols sh000001   # 指定标的
uv run daemon start               # 启动守护进程（前台）
uv run daemon start --detach      # 启动守护进程（后台）
uv run daemon stop                # 停止守护进程
uv run daemon status              # 查看运行状态
uv run daemon reload              # 热加载配置
uv run analyze                    # 生成分析报告
uv run maintain --dry-run         # 预览清理
uv run maintain                   # 执行清理 + 归档
pytest                            # 运行测试
```

## 关键约束

- 数据仓库四层: ODS → DWD → DWS → ADS（详见 README.md）
- DWD 去重: `current`/`volume`/`high`/`low` 任一变化才写入；ODS 照写
- API 编码: GB2312，需转 UTF-8；代码前缀 sh/sz/bj
- 并发: 标的<6 单线程，>=6 自动扩到 min(ceil(n/4), 4)
- 线程池只做 HTTP，结果入 Queue，主线程串行写 DB
- 配置: config.yaml（参考 config.example.yaml）
- 测试: pytest（tests/ 目录）
- 17 个源模块: config/db/fetcher/parser/storage/scheduler/logger/monitor/maintenance/crawler/analyze/daemon/session/health/reloader/reporter

## 守护进程

`uv run daemon` 管理采集生命周期：
- 按 `sessions` 配置的时间窗口自动开关采集
- 支持全局默认时段 + 个别 symbol 覆盖
- 配置热加载（SIGHUP 或 mtime 变化）
- 自动重启自愈（当日最大重试次数可配置）
- 本地 HTTP 健康检查（127.0.0.1:8089/healthz）
- 盘后自动报告 + 数据清理

## 架构详情

详见 README.md

# Recent Activity

<claude-mem-context>

### Jun 5, 2026
| ID    | Time    | T    | Title                                                        | Read |
| ----- | ------- | ---- | ------------------------------------------------------------ | ---- |
| #1402 | 5:18 PM | 🟣    | Step 4a 完成：新建 sina-hq-crawler/README.md                 | ~185 |
| #1370 | 3:37 PM | 🔵    | CLAUDE.md文档仍引用旧架构，需要更新为数据仓库分层设计        | ~117 |
| #1360 | 3:33 PM | 🟣    | Phase 4采集核心模块全部实现：fetcher/storage/scheduler/crawler | ~255 |
| #1344 | 3:24 PM | ✅    | 创建pyproject.toml项目配置                                   | ~74  |
| #1343 | "       | ⚖️    | 新浪财经行情采集器采用数据仓库分层架构重构                   | ~192 |
| #1330 | 2:57 PM | 🔵    | 爬虫项目架构限制全面分析结果                                 | ~173 |
| #1325 | 2:55 PM | 🔵    | 新浪行情爬虫项目结构探查                                     | ~163 |
| #1323 | 2:38 PM | ✅    | sina-hq-crawler项目完整结构确认                              | ~144 |
| #1322 | "       | 🟣    | 测试报告生成完成，数据质量评估结果确认                       | ~146 |
| #1321 | "       | 🟣    | 实现数据分析与报告生成脚本analyze.py                         | ~157 |
| #1319 | 2:32 PM | 🟣    | 实现Python实时行情采集器crawler.py                           | ~186 |
| #1318 | 2:31 PM | ✅    | 创建项目文档CLAUDE.md                                        | ~125 |
|       |         |      |                                                              |      |

</claude-mem-context>
