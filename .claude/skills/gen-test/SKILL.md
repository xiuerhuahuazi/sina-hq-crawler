---
name: gen-test
description: 为 sina-hq-crawler 项目生成符合现有约定的 pytest 测试
disable-model-invocation: true
---

# 测试生成器

为 sina-hq-crawler 项目生成符合现有约定的 pytest 测试。

## 使用方式

```
/gen-test <模块名>
```

例如：`/gen-test parser` 或 `/gen-test storage`

## 规则

1. **命名**: 测试文件 `test_<模块名>.py`，测试函数 `test_<场景描述>`
2. **Fixtures**: 使用 `conftest.py` 中的共享 fixtures：
   - `base_config` — 最小可用配置字典
   - `db_conn` — 内存 SQLite 连接（带完整表结构）
   - `db_conn_memory` — 纯内存 SQLite 连接
   - `sh_index_line` — 上证指数原始响应行
   - `bj_stock_line` — 北交所个股原始响应行
3. **Mock 策略**:
   - 外部 HTTP 请求 → `unittest.mock.patch` mock `requests.Session`
   - 磁盘 SQLite → 使用 `:memory:` 连接
   - 时间相关 → mock `time.time` / `time.monotonic`
   - 信号处理 → mock `signal.signal`
4. **覆盖要求**:
   - 正常路径（happy path）
   - 异常路径（网络错误、解析失败、空数据）
   - 边界条件（零值、None、空字符串、超长输入）
5. **风格**:
   - 每个测试函数只测一个行为
   - 使用 `pytest.raises` 测试异常
   - 使用 `pytest.mark.parametrize` 测试多组输入
   - 断言消息要描述预期行为
6. **数据仓库约定**:
   - ODS 层测试：验证原始数据完整保存
   - DWD 层测试：验证去重逻辑（current/volume/high/low）
   - DWS 层测试：验证聚合逻辑（open/high/low/close）
   - ADS 层测试：验证视图查询结果

## 示例

```python
import pytest
from src.parser import parse_quote, _float

class TestParseQuote:
    def test_valid_stock_line(self, bj_stock_line):
        result = parse_quote(bj_stock_line)
        assert result is not None
        assert result["symbol"] == "bj920576"
        assert result["name"] == "天力复合"

    def test_empty_line_returns_none(self):
        assert parse_quote("") is None

    def test_malformed_line_returns_none(self):
        assert parse_quote("not a valid line") is None

class TestFloat:
    @pytest.mark.parametrize("input,expected", [
        ("3.14", 3.14),
        ("", None),
        ("0", None),
        ("N/A", None),
    ])
    def test_float_conversion(self, input, expected):
        assert _float(input) == expected
```

## 输出

生成的测试文件内容，包含：
- 完整的 import 语句
- 所有必要 fixtures
- 正常/异常/边界三类测试
- 中文注释说明每个测试的意图
