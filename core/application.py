"""Application lifecycle management for SharipovAI OS.

The application object coordinates core infrastructure only. It initializes
configuration, logging, and application metadata without embedding business,
trading, or exchange-specific behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging

from .configuration import Config
from .constants import APP_DESCRIPTION
from .logger import create_logger


@dataclass(frozen=True, slots=True)
class ApplicationInfo:
    """Static application information.

    Attributes:
        name: Application name.
        version: Application version.
        description: Short application description.
        environment: Active runtime environment.
    """

    name: str
    version: str
    description: str
    environment: str


class Application:
    """Core application entry point.

    The class owns infrastructure startup and shutdown concerns while keeping
    domain behavior outside the core layer.
    """

    def __init__(self, config: Config | None = None) -> None:
        """Initialize the application.

        Args:
            config: Optional preloaded configuration. When omitted,
                configuration is loaded from the environment.
        """

        self._config = config or Config.load()
        self._logger = create_logger(
            name=self._config.app_name,
            level=self._config.log_level,
            log_path=self._config.log_path,
        )
        self._info = ApplicationInfo(
            name=self._config.app_name,
            version=self._config.app_version,
            description=APP_DESCRIPTION,
            environment=self._config.environment,
        )
        self._is_running = False

    @property
    def config(self) -> Config:
        """Return the active application configuration."""

        return self._config

    @property
    def logger(self) -> logging.Logger:
        """Return the configured application logger."""

        return self._logger

    @property
    def info(self) -> ApplicationInfo:
        """Return application metadata."""

        return self._info

    @property
    def version(self) -> str:
        """Return the application version."""

        return self._info.version

    @property
    def is_running(self) -> bool:
        """Return whether the application has been started."""

        return self._is_running

    def startup_message(self) -> str:
        """Build the startup message.

        Returns:
            Human-readable startup message.
        """

        return (
            f"{self.info.name} {self.info.version} starting "
            f"in {self.info.environment} environment."
        )

    def start(self) -> None:
        """Start core application infrastructure."""

        if self._is_running:
            self._logger.debug("%s is already running.", self.info.name)
            return

        self._logger.info(self.startup_message())
        self._is_running = True

    def shutdown(self) -> None:
        """Shutdown core application infrastructure."""

        if not self._is_running:
            self._logger.debug("%s is not running.", self.info.name)
            return

        self._logger.info("%s shutting down.", self.info.name)
        self._is_running = False
