"""日志配置：控制台彩色 + 文件落盘。"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_CONFIGURED = False

_FMT = "%(asctime)s | %(levelname)-7s | %(name)-22s | %(message)s"
_COLORS = {
    "DEBUG": "\033[36m",
    "INFO": "\033[32m",
    "WARNING": "\033[33m",
    "ERROR": "\033[31m",
    "CRITICAL": "\033[41m",
}
_RESET = "\033[0m"


class _ColorFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:  # noqa: A003
        text = super().format(record)
        color = _COLORS.get(record.levelname)
        if color and sys.stdout.isatty():
            return f"{color}{text}{_RESET}"
        return text


def setup_logging(level: str = "INFO", log_dir: Path | None = None) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    root = logging.getLogger()
    root.setLevel(level.upper())

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(_ColorFormatter(_FMT, datefmt="%H:%M:%S"))
    root.addHandler(console)

    if log_dir is not None:
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            fh = RotatingFileHandler(
                log_dir / "backend.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
            )
            fh.setFormatter(logging.Formatter(_FMT, datefmt="%Y-%m-%d %H:%M:%S"))
            root.addHandler(fh)
        except OSError:  # pragma: no cover - 只影响文件日志
            pass

    for noisy in ("httpx", "httpcore", "urllib3", "watchfiles", "qdrant_client"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)