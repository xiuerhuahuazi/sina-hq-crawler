#!/bin/bash
# WSL优化测试运行脚本

echo "=== 新浪行情采集系统测试 ==="
echo "检测WSL环境..."

# 检测WSL
if grep -qi microsoft /proc/version 2>/dev/null; then
    echo "✓ 检测到WSL环境，启用优化模式"
    WSL_MODE=true
else
    echo "✓ 标准Linux/Mac环境"
    WSL_MODE=false
fi

# 设置环境变量
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1

if [ "$WSL_MODE" = true ]; then
    # WSL优化：减少并发，增加超时
    echo "应用WSL优化设置..."
    export PYTEST_TIMEOUT=30
    export PYTEST_ADDOPTS="--timeout=30 -x --tb=short"
fi

# 运行测试
echo ""
echo "开始运行测试..."
echo "================================"

if [ "$WSL_MODE" = true ]; then
    # WSL上分组运行，避免资源争用
    echo "WSL模式：分组运行测试"
    echo ""

    echo "1/4 运行核心测试..."
    uv run pytest tests/test_config.py tests/test_parser.py tests/test_db.py -v --tb=short --timeout=30 || exit 1

    echo ""
    echo "2/4 运行存储和监控测试..."
    uv run pytest tests/test_storage.py tests/test_monitor.py -v --tb=short --timeout=30 || exit 1

    echo ""
    echo "3/4 运行调度和爬虫测试..."
    uv run pytest tests/test_scheduler.py tests/test_crawler.py -v --tb=short --timeout=30 || exit 1

    echo ""
    echo "4/4 运行守护进程和健康检查测试..."
    uv run pytest tests/test_daemon.py tests/test_health.py -v --tb=short --timeout=30 || exit 1
else
    # 标准模式：并行运行
    uv run pytest tests/ -v --tb=short --timeout=60
fi

echo ""
echo "================================"
echo "测试完成！"
