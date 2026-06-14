#!/bin/bash
# macOS环境优化测试运行脚本

echo "=== 新浪行情采集系统测试 (macOS优化版) ==="
echo "检测环境..."

# 检测macOS
if [[ "$(uname)" == "Darwin" ]]; then
    echo "✓ 检测到macOS环境"
    MACOS_MODE=true
else
    echo "✓ 非macOS环境"
    MACOS_MODE=false
fi

# 检测ARM64架构
if [[ "$(uname -m)" == "arm64" ]]; then
    echo "✓ ARM64架构 (Apple Silicon)"
    ARM64_MODE=true
else
    echo "✓ x86_64架构"
    ARM64_MODE=false
fi

# 设置环境变量
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1

# macOS优化设置
if [ "$MACOS_MODE" = true ]; then
    echo "应用macOS优化设置..."
    # macOS上可以使用更短的超时
    export PYTEST_TIMEOUT=20
    export PYTEST_ADDOPTS="--timeout=20 -v --tb=short"
fi

# ARM64优化
if [ "$ARM64_MODE" = true ]; then
    echo "ARM64架构优化..."
    # ARM64性能更好，但pytest-xdist未安装，使用单线程模式
    # 如需并行，可安装: uv pip install pytest-xdist
    echo "  (如需并行测试，可安装: uv pip install pytest-xdist)"
fi

# 运行测试
echo ""
echo "开始运行测试..."
echo "================================"

if [ "$MACOS_MODE" = true ]; then
    # macOS上可以直接并行运行
    echo "macOS模式：并行运行测试"
    echo ""

    # 运行所有测试
    uv run pytest tests/ -v --tb=short --timeout=20 --durations=10

    # 检查测试结果
    TEST_EXIT_CODE=$?
else
    # 其他系统使用默认方式
    uv run pytest tests/ -v --tb=short --timeout=30
    TEST_EXIT_CODE=$?
fi

echo ""
echo "================================"
echo "测试完成！"

# 显示测试统计
if [ $TEST_EXIT_CODE -eq 0 ]; then
    echo "✅ 所有测试通过"
else
    echo "❌ 部分测试失败 (退出码: $TEST_EXIT_CODE)"
fi

exit $TEST_EXIT_CODE
