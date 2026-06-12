"""ProjectScorer — 项目质量评分系统（推送资格门控）。"""

import ast
import json
import re
import subprocess
import sys
from pathlib import Path


class ProjectScorer:
    """评估项目质量，总分 >= 90 才有推送资格。

    评分维度：
    - 测试覆盖率 (30分)
    - 测试通过率 (15分)
    - 代码规范 (15分)
    - 模块数量 (10分)
    - 文档覆盖率 (10分)
    - 测试文件覆盖率 (10分)
    - 配置校验 (5分)
    - 无外部 API 硬编码 (5分)
    """

    THRESHOLD = 90

    def __init__(self, project_root: str | Path | None = None):
        self._root = Path(project_root) if project_root else Path(__file__).resolve().parent.parent.parent

    def score(self) -> dict:
        """返回 {"total": int, "breakdown": {...}, "eligible": bool}。"""
        breakdown = {
            "test_coverage": self.score_test_coverage(),
            "test_pass_rate": self.score_test_pass_rate(),
            "lint": self.score_lint(),
            "module_count": self.score_module_count(),
            "docstring_coverage": self.score_docstring_coverage(),
            "test_file_coverage": self.score_test_file_coverage(),
            "config_validation": self.score_config_validation(),
            "no_external_api_lock": self.score_no_external_api_lock(),
        }
        total = sum(breakdown.values())
        return {
            "total": total,
            "breakdown": breakdown,
            "eligible": total >= self.THRESHOLD,
        }

    def score_test_coverage(self) -> int:
        """运行 pytest --cov，解析覆盖率。0-30 分。"""
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "--cov=src", "--cov-report=json", "-q", "--tb=no"],
                cwd=self._root, capture_output=True, text=True, timeout=120,
            )
            json_file = self._root / "coverage.json"
            if json_file.exists():
                data = json.loads(json_file.read_text())
                pct = data.get("totals", {}).get("percent_covered", 0)
                json_file.unlink(missing_ok=True)
                return min(30, int(pct * 30 / 100))
        except Exception:
            pass
        return 0

    def score_test_pass_rate(self) -> int:
        """运行 pytest，解析通过率。0-15 分。"""
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "--tb=no"],
                cwd=self._root, capture_output=True, text=True, timeout=120,
            )
            # 解析 "X passed, Y failed"
            m = re.search(r"(\d+) passed", result.stdout)
            passed = int(m.group(1)) if m else 0
            m2 = re.search(r"(\d+) failed", result.stdout)
            failed = int(m2.group(1)) if m2 else 0
            total = passed + failed
            if total == 0:
                return 0
            return min(15, int(passed / total * 15))
        except Exception:
            return 0

    def score_lint(self) -> int:
        """运行 ruff check，统计错误数。0-15 分。"""
        try:
            result = subprocess.run(
                [sys.executable, "-m", "ruff", "check", "src/"],
                cwd=self._root, capture_output=True, text=True, timeout=30,
            )
            errors = len(result.stdout.strip().splitlines()) if result.stdout.strip() else 0
            if errors >= 50:
                return 0
            return max(0, 15 - int(errors * 15 / 50))
        except Exception:
            return 0

    def score_module_count(self) -> int:
        """统计 src/ 下的 .py 模块数。18+ 个 = 10 分。"""
        src_dir = self._root / "src"
        if not src_dir.exists():
            return 0
        modules = list(src_dir.rglob("*.py"))
        count = sum(1 for f in modules if f.name != "__init__.py" and "__pycache__" not in str(f))
        return min(10, int(count * 10 / 18))

    def score_docstring_coverage(self) -> int:
        """AST 遍历检查 docstring 覆盖率。0-10 分。"""
        src_dir = self._root / "src"
        if not src_dir.exists():
            return 0
        total = 0
        with_doc = 0
        for py_file in src_dir.rglob("*.py"):
            if "__pycache__" in str(py_file) or py_file.name == "__init__.py":
                continue
            try:
                tree = ast.parse(py_file.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        total += 1
                        if (node.body and isinstance(node.body[0], ast.Expr)
                                and isinstance(node.body[0].value, ast.Constant)
                                and isinstance(node.body[0].value.value, str)):
                            with_doc += 1
            except (SyntaxError, UnicodeDecodeError):
                pass
        if total == 0:
            return 10
        return min(10, int(with_doc / total * 10))

    def score_test_file_coverage(self) -> int:
        """测试文件与源文件的比值。1:1 = 10 分。"""
        src_dir = self._root / "src"
        tests_dir = self._root / "tests"
        if not src_dir.exists() or not tests_dir.exists():
            return 0
        src_modules = {f.stem for f in src_dir.rglob("*.py") if f.name != "__init__.py" and "__pycache__" not in str(f)}
        test_files = {f.stem.replace("test_", "") for f in tests_dir.glob("test_*.py")}
        if not src_modules:
            return 0
        covered = len(src_modules & test_files)
        return min(10, int(covered / len(src_modules) * 10))

    def score_config_validation(self) -> int:
        """验证 config.yaml 可正常解析。0 或 5 分。"""
        try:
            cfg_file = self._root / "config.yaml"
            if not cfg_file.exists():
                return 0
            from src.config import load_config
            config = load_config(str(cfg_file))
            # 检查必要键
            required = ["symbols", "crawl", "http", "database", "sessions", "daemon"]
            for key in required:
                if key not in config:
                    return 0
            return 5
        except Exception:
            return 0

    def score_no_external_api_lock(self) -> int:
        """检查 src/ 中是否有硬编码 URL（config.py 除外）。0 或 5 分。"""
        src_dir = self._root / "src"
        if not src_dir.exists():
            return 0
        url_re = re.compile(r'https?://[^\s"\'<>]+')
        config_file = src_dir / "config.py"
        violations = 0
        for py_file in src_dir.rglob("*.py"):
            if "__pycache__" in str(py_file):
                continue
            if py_file == config_file:
                continue  # config.py 的 URL 是配置默认值，允许
            try:
                content = py_file.read_text(encoding="utf-8")
                urls = url_re.findall(content)
                for url in urls:
                    # 排除注释中的 URL 和文档链接
                    if "example" in url.lower() or "github.com" in url.lower():
                        continue
                    # 检查是否在 config.py 的 _DEFAULTS 中
                    violations += 1
            except (UnicodeDecodeError, OSError):
                pass
        return 0 if violations > 0 else 5


def main():
    """CLI: uv run score。"""
    scorer = ProjectScorer()
    result = scorer.score()

    print(f"\n{'='*50}")
    print(f"  项目质量评分: {result['total']}/100")
    print(f"  推送资格: {'✅ 通过' if result['eligible'] else '❌ 未达标'} (需 >= {ProjectScorer.THRESHOLD})")
    print(f"{'='*50}\n")

    for name, score in result["breakdown"].items():
        max_scores = {
            "test_coverage": 30, "test_pass_rate": 15, "lint": 15,
            "module_count": 10, "docstring_coverage": 10,
            "test_file_coverage": 10, "config_validation": 5,
            "no_external_api_lock": 5,
        }
        max_s = max_scores.get(name, 0)
        bar = "█" * score + "░" * (max_s - score)
        print(f"  {name:25} {bar} {score}/{max_s}")

    print()
    return 0 if result["eligible"] else 1


if __name__ == "__main__":
    sys.exit(main())
