"""TOML configuration loader for SharipovAI OS."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping
import tomllib

from .models import AppConfig, MarketConfig, NewsConfig, PaperConfig, RiskConfig


def load_config(path: str | Path = "config/default.toml") -> AppConfig:
    """Load application configuration from a TOML file.

    Args:
        path: Path to the TOML configuration file.

    Returns:
        Parsed application configuration.
    """

    config_path = Path(path)
    with config_path.open("rb") as file:
        payload = tomllib.load(file)

    return _parse_app_config(payload)


def _parse_app_config(payload: Mapping[str, Any]) -> AppConfig:
    """Parse root application configuration."""

    return AppConfig(
        run_mode=str(payload["run_mode"]),
        paper=_parse_paper_config(_mapping(payload["paper"])),
        risk=_parse_risk_config(_mapping(payload["risk"])),
        news=_parse_news_config(_mapping(payload["news"])),
        market=_parse_market_config(_mapping(payload["market"])),
    )


def _parse_paper_config(payload: Mapping[str, Any]) -> PaperConfig:
    """Parse paper trading configuration."""

    return PaperConfig(initial_balance=float(payload["initial_balance"]))


def _parse_risk_config(payload: Mapping[str, Any]) -> RiskConfig:
    """Parse risk configuration."""

    return RiskConfig(
        max_drawdown=float(payload["max_drawdown"]),
        max_position_percent=float(payload["max_position_percent"]),
    )


def _parse_news_config(payload: Mapping[str, Any]) -> NewsConfig:
    """Parse news configuration."""

    return NewsConfig(rss_feeds=[str(feed) for feed in payload["rss_feeds"]])


def _parse_market_config(payload: Mapping[str, Any]) -> MarketConfig:
    """Parse market configuration."""

    return MarketConfig(
        exchange=str(payload["exchange"]),
        category=str(payload["category"]),
    )


def _mapping(value: Any) -> Mapping[str, Any]:
    """Return a value as a mapping.

    Args:
        value: Candidate mapping.

    Returns:
        Mapping value.

    Raises:
        TypeError: If the value is not a mapping.
    """

    if not isinstance(value, Mapping):
        raise TypeError("Configuration section must be a mapping.")
    return value
