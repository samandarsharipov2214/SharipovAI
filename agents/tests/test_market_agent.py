"""Tests for the deterministic Market Agent."""

from __future__ import annotations

from agents import MarketAgent
from bybit import TickerInfo
from core.orchestrator import AgentResult


def test_run_missing_tickers() -> None:
    """Missing tickers produce a failed agent result."""

    result = MarketAgent().run({})

    assert result.agent_name == "Market Agent"
    assert result.success is False
    assert result.confidence == 0.0
    assert result.data["error"] == "missing_tickers"


def test_run_empty_tickers() -> None:
    """Empty tickers produce a failed agent result."""

    result = MarketAgent().run({"tickers": []})

    assert result.success is False
    assert result.data["error"] == "missing_tickers"


def test_run_successful_run() -> None:
    """Valid tickers produce a successful agent result."""

    result = MarketAgent().run({"tickers": _tickers()})

    assert result.success is True
    assert result.agent_name == "Market Agent"
    assert result.confidence > 0
    assert "Top symbol" in result.summary


def test_run_top_symbol_selection() -> None:
    """The highest scored ticker is selected as top symbol."""

    result = MarketAgent().run({"tickers": _tickers()})

    assert result.data["top_symbol"] == "BTCUSDT"
    assert result.data["top_20_symbols"][0] == "BTCUSDT"


def test_run_factor_scores_included() -> None:
    """Factor scores are included for the top ticker."""

    result = MarketAgent().run({"tickers": _tickers()})

    factor_scores = result.data["factor_scores"]
    assert len(factor_scores) == 5
    assert {factor["name"] for factor in factor_scores} == {
        "Volume Factor",
        "Price Change Factor",
        "Liquidity Factor",
        "Volatility Factor",
        "Trend Factor",
    }


def test_run_agent_result_structure() -> None:
    """Market Agent returns the expected AgentResult structure."""

    result = MarketAgent().run({"tickers": _tickers()})

    assert isinstance(result, AgentResult)
    assert set(result.data) >= {
        "top_symbol",
        "top_score",
        "top_signal",
        "top_reason",
        "top_20_symbols",
        "factor_scores",
    }
    assert isinstance(result.data["top_score"], float)
    assert isinstance(result.data["top_20_symbols"], list)


def _tickers() -> list[TickerInfo]:
    """Create deterministic ticker fixtures."""

    return [
        TickerInfo(
            category="spot",
            symbol="ETHUSDT",
            last_price="2000",
            bid_price="1999",
            ask_price="2001",
            price_24h_change_percent="0.01",
            volume_24h="1000",
            turnover_24h="2000000",
        ),
        TickerInfo(
            category="spot",
            symbol="BTCUSDT",
            last_price="50000",
            bid_price="49990",
            ask_price="50010",
            price_24h_change_percent="0.03",
            volume_24h="2000",
            turnover_24h="10000000",
        ),
        TickerInfo(
            category="spot",
            symbol="XRPUSDT",
            last_price="1",
            bid_price="0.99",
            ask_price="1.01",
            price_24h_change_percent="-0.02",
            volume_24h="500",
            turnover_24h="500000",
        ),
    ]
