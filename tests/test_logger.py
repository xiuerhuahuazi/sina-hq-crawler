import logging
import pytest
from pathlib import Path
from src.logger import setup_logging, get_logger


class TestSetupLogging:
    def test_handlers_attached(self, base_config, tmp_path):
        log_file = tmp_path / "test.log"
        base_config["logging"]["file"] = str(log_file)
        setup_logging(base_config)
        root = logging.getLogger()
        assert len(root.handlers) >= 2  # console + file

    def test_log_file_created(self, base_config, tmp_path):
        log_file = tmp_path / "subdir" / "test.log"
        base_config["logging"]["file"] = str(log_file)
        setup_logging(base_config)
        assert log_file.parent.exists()

    def test_root_level_set(self, base_config, tmp_path):
        base_config["logging"]["level"] = "DEBUG"
        base_config["logging"]["file"] = str(tmp_path / "test.log")
        setup_logging(base_config)
        root = logging.getLogger()
        assert root.level == logging.DEBUG

    def test_handlers_cleared_on_reinit(self, base_config, tmp_path):
        base_config["logging"]["file"] = str(tmp_path / "test.log")
        setup_logging(base_config)
        count1 = len(logging.getLogger().handlers)
        setup_logging(base_config)
        count2 = len(logging.getLogger().handlers)
        assert count2 == count1  # no duplicates


class TestGetLogger:
    def test_returns_named_logger(self):
        logger = get_logger("test.module")
        assert logger.name == "test.module"
        assert isinstance(logger, logging.Logger)
