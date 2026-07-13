"""TOML configuration loader for SharipovAI OS."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping
import tomllib

from .models import AppConfig, MarketConfig, NewsConfig, PaperConfig, RiskConfig


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = Path(__file__).resolve().with_name("default.toml")


def load_config(path: str | Path | None = None) -> AppConfig:
    """Load application configuration from a TOML file.

    The built-in configuration is resolved relative to this package rather than
    the process working directory, so imports remain reliable from Docker exec,
    systemd, tests, and maintenance scripts.  Explicit relative paths continue
    to resolve from the caller's current directory when that file exists; when
    it does not, they fall back to the project root for backwards compatibility.

    Args:
        path: Optional path to a TOML configuration file.

    Returns:
        Parsed application configuration.
    """

    config_path = _resolve_config_path(path)
    with config_path.open("rb") as file:
        payload = tomllib.load(file)

    return _parse_app_config(payload)


def _resolve_config_path(path: str | Path | None) -> Path:
    if path is None:
        return DEFAULT_CONFIG_PATH

    candidate = Path(path).expanduser()
    if candidate.is_absolute() or candidate.exists():
        return candidate

    project_candidate = PROJECT_ROOT / candidate
    if project_candidate.exists():
        return project_candidate

    # Preserve the caller-facing error path when neither location exists.
    return candidate


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


__all__ = ["DEFAULT_CONFIG_PATH", "PROJECT_ROOT", "load_config"]
