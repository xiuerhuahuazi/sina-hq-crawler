#!/usr/bin/env python3
"""环境检测脚本 — 检查当前系统环境并验证项目兼容性。"""

import sys
import platform
import subprocess
import json
from pathlib import Path


def get_system_info():
    """获取系统信息。"""
    info = {
        "os": platform.system(),
        "os_version": platform.version(),
        "architecture": platform.machine(),
        "python_version": sys.version,
        "python_executable": sys.executable,
        "is_macos": platform.system() == "Darwin",
        "is_linux": platform.system() == "Linux",
        "is_wsl": False,
        "is_arm64": platform.machine() == "arm64",
        "is_x86_64": platform.machine() == "x86_64",
    }

    # 检测WSL
    if info["is_linux"]:
        try:
            with open('/proc/version', 'r') as f:
                version_info = f.read().lower()
                info["is_wsl"] = "microsoft" in version_info
        except:
            pass

    return info


def check_uv_environment():
    """检查uv环境。"""
    try:
        result = subprocess.run(
            ["uv", "run", "python", "--version"],
            capture_output=True,
            text=True,
            timeout=10
        )
        return {
            "installed": True,
            "version": result.stdout.strip() if result.returncode == 0 else None,
            "error": result.stderr if result.returncode != 0 else None
        }
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return {"installed": False, "version": None, "error": "uv not found"}


def check_project_dependencies():
    """检查项目依赖。"""
    pyproject_path = Path("pyproject.toml")
    if not pyproject_path.exists():
        return {"error": "pyproject.toml not found"}

    try:
        result = subprocess.run(
            ["uv", "pip", "list"],
            capture_output=True,
            text=True,
            timeout=10
        )
        installed_packages = {}
        for line in result.stdout.split('\n')[2:]:  # 跳过标题行
            if line.strip():
                parts = line.split()
                if len(parts) >= 2:
                    installed_packages[parts[0]] = parts[1]

        return {"packages": installed_packages}
    except Exception as e:
        return {"error": str(e)}


def check_compatibility():
    """检查兼容性。"""
    info = get_system_info()
    uv_info = check_uv_environment()
    deps_info = check_project_dependencies()

    compatibility = {
        "system": info,
        "uv": uv_info,
        "dependencies": deps_info,
        "recommendations": [],
        "warnings": [],
    }

    # 检查Python版本
    python_version = sys.version_info
    if python_version < (3, 13):
        compatibility["warnings"].append(
            f"Python版本 {python_version.major}.{python_version.minor} 低于项目要求的 3.13+"
        )
    else:
        compatibility["recommendations"].append("✓ Python版本符合要求")

    # 检查架构
    if info["is_arm64"]:
        compatibility["recommendations"].append("✓ ARM64架构，性能优秀")
    elif info["is_x86_64"]:
        compatibility["recommendations"].append("✓ x86_64架构，兼容性好")

    # 检查操作系统
    if info["is_macos"]:
        compatibility["recommendations"].append("✓ macOS环境，支持良好")
    elif info["is_linux"]:
        if info["is_wsl"]:
            compatibility["recommendations"].append("✓ WSL环境，已优化")
        else:
            compatibility["recommendations"].append("✓ Linux环境，完全支持")

    # 检查uv
    if uv_info["installed"]:
        compatibility["recommendations"].append("✓ uv已安装")
    else:
        compatibility["warnings"].append("uv未安装，请先安装uv")

    return compatibility


def print_report(compatibility):
    """打印检测报告。"""
    print("=" * 60)
    print("环境检测报告")
    print("=" * 60)

    # 系统信息
    system = compatibility["system"]
    print("\n【系统信息】")
    print(f"操作系统: {system['os']} {system['os_version']}")
    print(f"架构: {system['architecture']}")
    print(f"Python: {system['python_version'].split()[0]}")
    print(f"WSL环境: {'是' if system['is_wsl'] else '否'}")

    # uv信息
    uv_info = compatibility["uv"]
    print("\n【uv环境】")
    if uv_info["installed"]:
        print(f"状态: 已安装")
        print(f"Python版本: {uv_info['version']}")
    else:
        print(f"状态: 未安装")
        print(f"错误: {uv_info['error']}")

    # 依赖信息
    deps = compatibility["dependencies"]
    if "packages" in deps:
        print("\n【已安装包】")
        print(f"总包数: {len(deps['packages'])}")
        # 显示关键包
        key_packages = ["requests", "pyyaml", "pytest", "pytest-cov"]
        for pkg in key_packages:
            if pkg in deps["packages"]:
                print(f"  {pkg}: {deps['packages'][pkg]}")

    # 兼容性检查
    print("\n【兼容性检查】")
    if compatibility["warnings"]:
        print("⚠️  警告:")
        for warning in compatibility["warnings"]:
            print(f"  - {warning}")

    if compatibility["recommendations"]:
        print("✅ 推荐:")
        for rec in compatibility["recommendations"]:
            print(f"  - {rec}")

    # 优化建议
    print("\n【优化建议】")
    if system["is_wsl"]:
        print("1. 使用WSL优化脚本: ./run_tests_wsl.sh")
        print("2. 设置测试超时: --timeout=30")
        print("3. 分组运行测试避免资源争用")
    elif system["is_macos"]:
        print("1. macOS环境，支持所有功能")
        print("2. ARM64架构性能优秀")
        print("3. 可直接运行: uv run pytest tests/")
    elif system["is_linux"]:
        print("1. Linux环境，完全支持")
        print("2. 可直接运行: uv run pytest tests/")

    print("\n" + "=" * 60)


def main():
    """主函数。"""
    try:
        compatibility = check_compatibility()
        print_report(compatibility)

        # 保存检测结果到文件
        output_file = Path("environment_report.json")
        # 移除不可序列化的内容
        serializable = {
            "system": compatibility["system"],
            "uv": compatibility["uv"],
            "recommendations": compatibility["recommendations"],
            "warnings": compatibility["warnings"],
        }
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(serializable, f, indent=2, ensure_ascii=False)
        print(f"\n详细报告已保存到: {output_file}")

    except Exception as e:
        print(f"检测失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
