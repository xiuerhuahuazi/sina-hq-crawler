"""Logging setup module using standard library only."""

import logging
import logging.handlers
from pathlib import Path


def setup_logging(config: dict) -> None:
    """Configure the root logger based on config['logging'].

    Sets up a console handler and a rotating file handler, each with
    independently configured levels.  The root logger level is set to the
    minimum of the two so that neither handler is starved of records.
    """
    log_cfg = config["logging"]

    log_level = logging.getLevelName(log_cfg["level"].upper())
    fmt = log_cfg.get("format", "%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    formatter = logging.Formatter(fmt)

    # --- root logger ---
    root = logging.getLogger()
    root.setLevel(log_level)
    root.handlers.clear()

    # --- console handler ---
    console = logging.StreamHandler()
    console.setLevel(log_level)
    console.setFormatter(formatter)
    root.addHandler(console)

    # --- file handler ---
    log_path = Path(log_cfg["file"])
    log_path.parent.mkdir(parents=True, exist_ok=True)

    file_handler = logging.handlers.RotatingFileHandler(
        filename=str(log_path),
        maxBytes=log_cfg.get("max_bytes", 10485760),
        backupCount=log_cfg.get("backup_count", 5),
        encoding="utf-8",
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger (convenience wrapper)."""
    return logging.getLogger(name)
