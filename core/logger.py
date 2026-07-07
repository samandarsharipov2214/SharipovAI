"""Logging infrastructure for SharipovAI OS.

The logger uses only the Python standard library and configures both console
and file handlers. Colored console output is enabled when the terminal appears
to support it.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path


LOG_FORMAT: str = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"


class ColorFormatter(logging.Formatter):
    """Logging formatter that optionally colors level names for console output."""

    _COLORS: dict[int, str] = {
        logging.DEBUG: "\033[36m",
        logging.INFO: "\033[32m",
        logging.WARNING: "\033[33m",
        logging.ERROR: "\033[31m",
        logging.CRITICAL: "\033[35m",
    }
    _RESET: str = "\033[0m"

    def __init__(self, fmt: str, datefmt: str | None = None, use_color: bool = True) -> None:
        """Initialize the formatter.

        Args:
            fmt: Log message format.
            datefmt: Optional datetime format.
            use_color: Whether ANSI colors should be applied.
        """

        super().__init__(fmt=fmt, datefmt=datefmt)
        self._use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        """Format a log record.

        Args:
            record: Log record emitted by the logging system.

        Returns:
            Formatted log message.
        """

        original_levelname = record.levelname
        if self._use_color:
            color = self._COLORS.get(record.levelno)
            if color is not None:
                record.levelname = f"{color}{record.levelname}{self._RESET}"

        try:
            return super().format(record)
        finally:
            record.levelname = original_levelname


def create_logger(
    name: str,
    level: str = "INFO",
    log_path: Path | str | None = None,
    *,
    enable_console: bool = True,
    enable_file: bool = True,
) -> logging.Logger:
    """Create and configure a project logger.

    Args:
        name: Logger name.
        level: Logging level name.
        log_path: Optional file path for persistent logs.
        enable_console: Whether to attach a console handler.
        enable_file: Whether to attach a file handler.

    Returns:
        Configured ``logging.Logger`` instance.
    """

    logger = logging.getLogger(name)
    logger.setLevel(_resolve_log_level(level))
    logger.propagate = False
    logger.handlers.clear()

    if enable_console:
        logger.addHandler(_create_console_handler(level))

    if enable_file and log_path is not None:
        logger.addHandler(_create_file_handler(Path(log_path), level))

    return logger


def _create_console_handler(level: str) -> logging.Handler:
    """Create a console logging handler.

    Args:
        level: Logging level name.

    Returns:
        Configured console handler.
    """

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(_resolve_log_level(level))
    handler.setFormatter(
        ColorFormatter(
            fmt=LOG_FORMAT,
            datefmt=DATE_FORMAT,
            use_color=sys.stdout.isatty(),
        )
    )
    return handler


def _create_file_handler(log_path: Path, level: str) -> logging.Handler:
    """Create a file logging handler.

    Args:
        log_path: Destination path for log output.
        level: Logging level name.

    Returns:
        Configured file handler.
    """

    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setLevel(_resolve_log_level(level))
    handler.setFormatter(logging.Formatter(fmt=LOG_FORMAT, datefmt=DATE_FORMAT))
    return handler


def _resolve_log_level(level: str) -> int:
    """Resolve a logging level name to its numeric value.

    Args:
        level: Logging level name.

    Returns:
        Numeric logging level.
    """

    return logging.getLevelName(level.upper())
