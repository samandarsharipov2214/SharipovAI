"""Application constants for SharipovAI OS.

This module contains stable application metadata and default infrastructure
values. It must not contain business, trading, or exchange-specific logic.
"""

from pathlib import Path


APP_NAME: str = "SharipovAI OS"
APP_VERSION: str = "0.1.0-alpha"
APP_DESCRIPTION: str = (
    "AI operating system for market analysis, capital management, "
    "and investment decision support."
)

DEFAULT_ENVIRONMENT: str = "development"
DEFAULT_LOG_LEVEL: str = "INFO"
DEFAULT_LOG_DIR: Path = Path("logs")
DEFAULT_LOG_FILE: str = "sharipovai.log"

ENV_PREFIX: str = "SHARIPOVAI_"
ENV_APP_NAME: str = f"{ENV_PREFIX}APP_NAME"
ENV_APP_VERSION: str = f"{ENV_PREFIX}APP_VERSION"
ENV_ENVIRONMENT: str = f"{ENV_PREFIX}ENVIRONMENT"
ENV_LOG_LEVEL: str = f"{ENV_PREFIX}LOG_LEVEL"
ENV_LOG_DIR: str = f"{ENV_PREFIX}LOG_DIR"
ENV_LOG_FILE: str = f"{ENV_PREFIX}LOG_FILE"

SUPPORTED_LOG_LEVELS: frozenset[str] = frozenset(
    {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
)
