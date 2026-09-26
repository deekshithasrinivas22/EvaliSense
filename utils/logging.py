"""Structured logging for EvaliSense.

Provides a consistent logger factory and an optional one-time setup
call that configures the root logger with level, format, and optional
file handler.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path


_DEFAULT_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_CONFIGURED = False


def setup_logging(
    level: str = "INFO",
    log_file: str | Path | None = None,
    fmt: str = _DEFAULT_FORMAT,
) -> None:
    """Configure the root logger once.

    Subsequent calls are silently ignored so that multiple modules
    can safely call ``setup_logging()`` at import time.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return
    _CONFIGURED = True

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    formatter = logging.Formatter(fmt)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    root.addHandler(console)

    if log_file is not None:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(str(path), encoding="utf-8")
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger for a module."""
    return logging.getLogger(name)
