"""Configuration loading for SharipovAI OS.

The configuration layer reads application settings from environment variables
and exposes them through an immutable value object. It intentionally avoids
business, trading, and exchange-specific configuration.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from .constants import (
    APP_NAME,
    APP_VERSION,
    DEFAULT_ENVIRONMENT,
    DEFAULT_LOG_DIR,
    DEFAULT_LOG_FILE,
    DEFAULT_LOG_LEVEL,
    ENV_APP_NAME,
    ENV_APP_VERSION,
    ENV_ENVIRONMENT,
    ENV_LOG_DIR,
    ENV_LOG_FILE,
    ENV_LOG_LEVEL,
    SUPPORTED_LOG_LEVELS,
)
from .exceptions import ConfigurationError


@dataclass(frozen=True, slots=True)
class Config:
    """Immutable application configuration.

    Attributes:
        app_name: Human-readable application name.
        app_version: Current application version.
        environment: Runtime environment name.
        log_level: Logging verbosity level.
        log_dir: Directory used for application log files.
        log_file: File name used by the file logger.
    """

    app_name: str
    app_version: str
    environment: str
    log_level: str
    log_dir: Path
    log_file: str

    @classmethod
    def load(cls, environ: Mapping[str, str] | None = None) -> Config:
        """Load configuration from environment variables.

        Args:
            environ: Optional mapping of environment values. When omitted,
                ``os.environ`` is used.

        Returns:
            A validated ``Config`` instance.

        Raises:
            ConfigurationError: If any configuration value is invalid.
        """

        source = MappingProxyType(dict(os.environ if environ is None else environ))
        config = cls(
            app_name=_read_text(source, ENV_APP_NAME, APP_NAME),
            app_version=_read_text(source, ENV_APP_VERSION, APP_VERSION),
            environment=_read_text(source, ENV_ENVIRONMENT, DEFAULT_ENVIRONMENT),
            log_level=_read_text(source, ENV_LOG_LEVEL, DEFAULT_LOG_LEVEL).upper(),
            log_dir=Path(_read_text(source, ENV_LOG_DIR, str(DEFAULT_LOG_DIR))),
            log_file=_read_text(source, ENV_LOG_FILE, DEFAULT_LOG_FILE),
        )
        config.validate()
        return config

    @property
    def log_path(self) -> Path:
        """Return the full log file path."""

        return self.log_dir / self.log_file

    def validate(self) -> None:
        """Validate configuration values.

        Raises:
            ConfigurationError: If required values are empty or unsupported.
        """

        required_values: Mapping[str, str] = {
            "app_name": self.app_name,
            "app_version": self.app_version,
            "environment": self.environment,
            "log_level": self.log_level,
            "log_file": self.log_file,
        }

        for field_name, value in required_values.items():
            if not value.strip():
                raise ConfigurationError(f"Configuration value '{field_name}' is required.")

        if self.log_level not in SUPPORTED_LOG_LEVELS:
            supported_levels = ", ".join(sorted(SUPPORTED_LOG_LEVELS))
            raise ConfigurationError(
                f"Unsupported log level '{self.log_level}'. "
                f"Supported values: {supported_levels}."
            )

        if self.log_dir.name == "":
            raise ConfigurationError("Configuration value 'log_dir' is required.")


def _read_text(source: Mapping[str, str], key: str, default: str) -> str:
    """Read a stripped string value from a mapping.

    Args:
        source: Mapping used as the configuration source.
        key: Configuration key to read.
        default: Default value used when the key is missing.

    Returns:
        The stripped configuration value.
    """

    return source.get(key, default).strip()
