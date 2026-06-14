#!/bin/bash
# 通用测试运行脚本 — 自动检测环境并应用优化

set -e  # 遇到错误立即退出

echo "=== 新浪行情采集系统测试 ==="
echo "自动检测环境..."

# 获取环境信息
get_environment() {
    local os_type="unknown"
    local arch="unknown"
    local is_wsl=false
    local is_macos=false
    local is_linux=false

    # 检测操作系统
    case "$(uname -s)" in
        Darwin*)
            os_type="macOS"
            is_macos=true
            ;;
        Linux*)
            os_type="Linux"
            is_linux=true
            ;;
        CYGWIN*|MINGW*|MSYS*)
            os_type="Windows"
            ;;
        *)
            os_type="Unknown"
            ;;
    esac

    # 检测架构
    case "$(uname -m)" in
        x86_64*)
            arch="x86_64"
            ;;
        arm64*|aarch64*)
            arch="ARM64"
            ;;
        *)
            arch="Unknown"
            ;;
    esac

    # 检测WSL
    if [ "$is_linux" = true ]; then
        if grep -qi microsoft /proc/version 2>/dev/null; then
            is_wsl=true
            os_type="WSL"
        fi
    fi

    echo "$os_type|$arch|$is_wsl|$is_macos|$is_linux"
}

# 获取环境信息
ENV_INFO=$(get_environment)
IFS='|' read -r OS_TYPE ARCH IS_WSL IS_MACOS IS_LINUX <<< "$ENV_INFO"

echo "✓ 操作系统: $OS_TYPE"
echo "✓ 架构: $ARCH"

# 根据环境选择优化策略
TIMEOUT=20
EXTRA_ARGS=""

if [ "$IS_WSL" = "true" ]; then
    echo "✓ WSL环境，应用WSL优化"
    TIMEOUT=30
    # WSL上分组运行
    echo ""
    echo "WSL模式：分组运行测试"
    echo ""

    echo "1/4 运行核心测试..."
    uv run pytest tests/test_config.py tests/test_parser.py tests/test_db.py -v --tb=short --timeout=$TIMEOUT || exit 1

    echo ""
    echo "2/4 运行存储和监控测试..."
    uv run pytest tests/test_storage.py tests/test_monitor.py -v --tb=short --timeout=$TIMEOUT || exit 1

    echo ""
    echo "3/4 运行调度和爬虫测试..."
    uv run pytest tests/test_scheduler.py tests/test_crawler.py -v --tb=short --timeout=$TIMEOUT || exit 1

    echo ""
    echo "4/4 运行守护进程和健康检查测试..."
    uv run pytest tests/test_daemon.py tests/test_health.py -v --tb=short --timeout=$TIMEOUT || exit 1

elif [ "$IS_MACOS" = "true" ]; then
    echo "✓ macOS环境，应用macOS优化"
    TIMEOUT=20

    if [ "$ARCH" = "ARM64" ]; then
        echo "✓ ARM64架构，性能优秀"
    fi

    # macOS上直接运行
    echo ""
    echo "macOS模式：直接运行测试"
    echo ""
    uv run pytest tests/ -v --tb=short --timeout=$TIMEOUT --durations=10

elif [ "$IS_LINUX" = "true" ]; then
    echo "✓ Linux环境，应用标准优化"
    TIMEOUT=20

    # Linux上直接运行
    echo ""
    echo "Linux模式：直接运行测试"
    echo ""
    uv run pytest tests/ -v --tb=short --timeout=$TIMEOUT --durations=10

else
    echo "⚠️  未知环境，使用默认配置"
    TIMEOUT=30
    uv run pytest tests/ -v --tb=short --timeout=$TIMEOUT
fi

TEST_EXIT_CODE=$?

echo ""
echo "================================"
echo "测试完成！"

# 显示测试统计
if [ $TEST_EXIT_CODE -eq 0 ]; then
    echo "✅ 所有测试通过"
else
    echo "❌ 部分测试失败 (退出码: $TEST_EXIT_CODE)"
fi

# 显示环境优化建议
echo ""
echo "【环境优化建议】"
if [ "$IS_WSL" = "true" ]; then
    echo "1. 考虑升级到WSL2以获得更好的性能"
    echo "2. 使用分组运行避免资源争用"
    echo "3. 监控资源使用: top -p \$(pgrep -f pytest)"
elif [ "$IS_MACOS" = "true" ]; then
    echo "1. macOS环境已完全优化"
    echo "2. ARM64架构性能优秀"
    echo "3. 可使用Activity Monitor监控资源"
elif [ "$IS_LINUX" = "true" ]; then
    echo "1. Linux环境性能最佳"
    echo "2. 可使用top/htop监控资源"
fi

exit $TEST_EXIT_CODE
