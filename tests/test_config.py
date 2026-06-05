import pytest
from pathlib import Path
from src.config import _deep_merge, _validate, _DEFAULTS, load_config


class TestDeepMerge:
    def test_new_key_added(self):
        base = {"a": 1}
        result = _deep_merge(base, {"b": 2})
        assert result == {"a": 1, "b": 2}

    def test_existing_key_overridden(self):
        base = {"a": 1}
        result = _deep_merge(base, {"a": 99})
        assert result == {"a": 99}

    def test_nested_dict_merged(self):
        base = {"db": {"host": "localhost", "port": 5432}}
        result = _deep_merge(base, {"db": {"port": 3306}})
        assert result == {"db": {"host": "localhost", "port": 3306}}

    def test_base_not_mutated(self):
        base = {"a": {"b": 1}}
        _deep_merge(base, {"a": {"c": 2}})
        assert base == {"a": {"b": 1}}

    def test_deep_nested(self):
        base = {"a": {"b": {"c": 1}}}
        result = _deep_merge(base, {"a": {"b": {"d": 2}}})
        assert result == {"a": {"b": {"c": 1, "d": 2}}}


class TestValidate:
    def test_empty_symbols_raises(self):
        with pytest.raises(ValueError, match="symbols"):
            _validate({"symbols": [], "crawl": {"poll_interval": 3}, "http": {"api_url": "https://x?ts={ts}&s={symbols}"}})

    def test_non_list_symbols_raises(self):
        with pytest.raises(ValueError, match="symbols"):
            _validate({"symbols": "sh000001", "crawl": {"poll_interval": 3}, "http": {"api_url": "https://x?ts={ts}&s={symbols}"}})

    def test_poll_interval_zero_raises(self):
        with pytest.raises(ValueError, match="poll_interval"):
            _validate({"symbols": ["sh000001"], "crawl": {"poll_interval": 0}, "http": {"api_url": "https://x?ts={ts}&s={symbols}"}})

    def test_poll_interval_negative_raises(self):
        with pytest.raises(ValueError, match="poll_interval"):
            _validate({"symbols": ["sh000001"], "crawl": {"poll_interval": -1}, "http": {"api_url": "https://x?ts={ts}&s={symbols}"}})

    def test_missing_ts_placeholder_raises(self):
        with pytest.raises(ValueError, match="api_url"):
            _validate({"symbols": ["sh000001"], "crawl": {"poll_interval": 3}, "http": {"api_url": "https://x?s={symbols}"}})

    def test_missing_symbols_placeholder_raises(self):
        with pytest.raises(ValueError, match="api_url"):
            _validate({"symbols": ["sh000001"], "crawl": {"poll_interval": 3}, "http": {"api_url": "https://x?ts={ts}"}})

    def test_valid_config_passes(self):
        _validate({
            "symbols": ["sh000001"],
            "crawl": {"poll_interval": 3},
            "http": {"api_url": "https://hq.sinajs.cn/rn={ts}&list={symbols}"},
        })


class TestLoadConfig:
    def test_explicit_valid_path(self, tmp_path):
        cfg_file = tmp_path / "cfg.yaml"
        cfg_file.write_text("symbols:\n  - sh000001\n", encoding="utf-8")
        cfg = load_config(str(cfg_file))
        assert cfg["symbols"] == ["sh000001"]
        assert cfg["crawl"]["poll_interval"] == 3  # default merged

    def test_explicit_missing_path_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_config(str(tmp_path / "nonexistent.yaml"))

    def test_empty_yaml_raises_validation(self, tmp_path):
        cfg_file = tmp_path / "empty.yaml"
        cfg_file.write_text("", encoding="utf-8")
        with pytest.raises(ValueError):
            load_config(str(cfg_file))

    def test_partial_override(self, tmp_path):
        cfg_file = tmp_path / "partial.yaml"
        cfg_file.write_text("symbols:\n  - sz000001\ncrawl:\n  poll_interval: 5\n", encoding="utf-8")
        cfg = load_config(str(cfg_file))
        assert cfg["symbols"] == ["sz000001"]
        assert cfg["crawl"]["poll_interval"] == 5
        assert cfg["database"]["wal_mode"] is True  # default preserved

    def test_default_path_with_symbols_in_config(self, tmp_path):
        import src.config as cfg_mod
        fake_src = tmp_path / "src"
        fake_src.mkdir()
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text("symbols:\n  - sh600519\n", encoding="utf-8")
        original_file = cfg_mod.__file__
        cfg_mod.__file__ = str(fake_src / "config.py")
        try:
            cfg = load_config()
            assert cfg["symbols"] == ["sh600519"]
        finally:
            cfg_mod.__file__ = original_file
