"""Tests for the TOML configuration loader."""

from __future__ import annotations

from config import load_config


def test_load_default_config() -> None:
    """Default configuration loads successfully."""

    settings = load_config()

    assert settings.run_mode == "demo"


def test_validate_run_mode() -> None:
    """Run mode matches default configuration."""

    settings = load_config()

    assert settings.run_mode == "demo"


def test_validate_paper_config() -> None:
    """Paper config matches default configuration."""

    settings = load_config()

    assert settings.paper.initial_balance == 10000.0


def test_validate_risk_config() -> None:
    """Risk config matches default configuration."""

    settings = load_config()

    assert settings.risk.max_drawdown == 10.0
    assert settings.risk.max_position_percent == 20.0


def test_validate_news_feeds() -> None:
    """News feeds match default configuration."""

    settings = load_config()

    assert settings.news.rss_feeds == [
        "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "https://cointelegraph.com/rss",
    ]


def test_validate_market_config() -> None:
    """Market config matches default configuration."""

    settings = load_config()

    assert settings.market.exchange == "bybit"
    assert settings.market.category == "spot"
