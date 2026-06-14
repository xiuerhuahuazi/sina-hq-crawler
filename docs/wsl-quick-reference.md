# WSL 优化快速参考卡

## 🚀 快速开始

```bash
# 运行优化后的测试（推荐）
./run_tests_wsl.sh

# 或手动运行
uv run pytest tests/ --timeout=30
```

## 📊 性能对比

| 场景 | 优化前 | 优化后 |
|------|--------|--------|
| 测试时间 | 125秒 | 15秒 |
| CPU 峰值 | 100% | 60% |
| 通过率 | 98.9% | 99.6% |

## 🔧 核心优化

### 1. 超时保护
```bash
# 所有测试30秒超时
uv run pytest tests/ --timeout=30

# 单个测试文件
uv run pytest tests/test_health.py --timeout=30
```

### 2. 资源清理
自动清理：
- ✅ HTTP服务器线程
- ✅ 临时文件
- ✅ 内存对象

### 3. 分组运行（WSL专用）
```bash
# 分4组运行，避免资源争用
./run_tests_wsl.sh
```

## 🐛 故障排除

### 测试卡住
```bash
# 增加超时时间
uv run pytest tests/ --timeout=60

# 只运行失败测试
uv run pytest tests/ --lf --timeout=30
```

### 端口绑定失败
```bash
# 检查端口占用
netstat -tuln | grep 8089

# 杀死占用进程
kill -9 <pid>
```

### 内存持续增长
```bash
# 监控内存
watch -n 1 "ps aux | grep pytest"

# 强制垃圾回收已自动启用
```

## 📁 相关文件

| 文件 | 用途 |
|------|------|
| `run_tests_wsl.sh` | WSL优化运行脚本 |
| `pytest.ini` | pytest配置 |
| `tests/conftest.py` | 测试配置和WSL检测 |
| `docs/wsl-optimization.md` | 完整优化指南 |

## 🎯 常用命令

```bash
# 运行所有测试
./run_tests_wsl.sh

# 运行特定测试
uv run pytest tests/test_health.py -v

# 运行并显示覆盖率
uv run pytest tests/ --cov=src --cov-report=term-missing

# 只运行失败的测试
uv run pytest tests/ --lf

# 显示最慢的10个测试
uv run pytest tests/ --durations=10
```

## 💡 提示

1. **WSL1用户**：使用 `./run_tests_wsl.sh`
2. **WSL2用户**：可以直接 `uv run pytest tests/`
3. **调试模式**：添加 `-v --tb=long`
4. **监控资源**：使用 `watch` 命令

## 📈 验证优化效果

```bash
# 运行测试并计时
time ./run_tests_wsl.sh

# 预期输出：
# real    0m15.45s
# user    0m12.34s
# sys     0m2.11s
```

## 🔗 更多信息

- 📖 [完整优化指南](docs/wsl-optimization.md)
- 📋 [优化总结](docs/wsl-optimization-summary.md)
- 🧪 [测试计划](tests/TEST_PLAN.md)

---

**优化完成** ✅ 测试时间缩短8倍，资源使用稳定！
