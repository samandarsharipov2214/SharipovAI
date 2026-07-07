"""Typed configuration models for SharipovAI OS."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PaperConfig:
    """Paper trading configuration.

    Attributes:
        initial_balance: Initial virtual paper trading balance.
    """

    initial_balance: float


@dataclass(frozen=True, slots=True)
class RiskConfig:
    """Risk configuration.

    Attributes:
        max_drawdown: Maximum allowed drawdown percentage.
        max_position_percent: Maximum allowed single-position percentage.
    """

    max_drawdown: float
    max_position_percent: float


@dataclass(frozen=True, slots=True)
class NewsConfig:
    """News configuration.

    Attributes:
        rss_feeds: RSS feed URLs.
    """

    rss_feeds: list[str]


@dataclass(frozen=True, slots=True)
class MarketConfig:
    """Market configuration.

    Attributes:
        exchange: Market data exchange identifier.
        category: Market data category.
    """

    exchange: str
    category: str


@dataclass(frozen=True, slots=True)
class AppConfig:
    """Root application configuration.

    Attributes:
        run_mode: Application run mode.
        paper: Paper trading configuration.
        risk: Risk configuration.
        news: News configuration.
        market: Market configuration.
    """

    run_mode: str
    paper: PaperConfig
    risk: RiskConfig
    news: NewsConfig
    market: MarketConfig
