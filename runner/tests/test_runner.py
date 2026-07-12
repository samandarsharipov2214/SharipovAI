"""Tests for the non-executable legacy SharipovAI runner."""

from __future__ import annotations

from pathlib import Path

import config.settings as config_settings
from bybit import TickerInfo
from config.models import AppConfig, MarketConfig, NewsConfig, PaperConfig, RiskConfig
from data_layer.providers import LiveMarketProvider, LiveRSSProvider
from memory import MemoryEngine
from paper_trading import PaperEngine
from runner import RunnerError, RunnerOutput, SharipovAIRunner


def test_runner_executes(tmp_path: Path) -> None:
    output = _runner(tmp_path).run()
    assert isinstance(output, RunnerOutput)
    assert output.decision == "NO_DECISION"


def test_market_agent_is_used(tmp_path: Path) -> None:
    runner = _runner(tmp_path)
    runner.run()
    assert runner.last_orchestrator is not None
    assert "Market Agent" in runner.last_orchestrator.list_agents()


def test_news_agent_is_used(tmp_path: Path) -> None:
    runner = _runner(tmp_path)
    runner.run()
    assert runner.last_orchestrator is not None
    assert "News Agent" in runner.last_orchestrator.list_agents()


def test_paper_account_exists_without_positions(tmp_path: Path) -> None:
    output = _runner(tmp_path).run()
    assert output.paper_cash == 10000.0
    assert output.paper_equity == 10000.0
    assert output.open_positions == 0
    assert output.paper_pnl == 0.0


def test_legacy_runner_does_not_train_learning(tmp_path: Path) -> None:
    output = _runner(tmp_path).run()
    assert output.learning_summary.total_trades == 0
    assert "not eligible" in output.reason


def test_report_is_generated_and_labeled(tmp_path: Path) -> None:
    output = _runner(tmp_path).run()
    assert "SharipovAI legacy runner completed." in output.report
    assert "LEGACY_OFFLINE_DIAGNOSTIC" in output.report
    assert "Execution eligible: false" in output.report
    assert "Learning eligible: false" in output.report
    assert "Published decision: NO_DECISION" in output.report


def test_no_real_api_calls_or_execution_evidence(tmp_path: Path) -> None:
    output = _runner(tmp_path).run()
    assert output.report
    assert output.portfolio_value > 0
    assert output.decision == "NO_DECISION"
    assert output.confidence == 0.0


def test_demo_mode_uses_static_providers(tmp_path: Path) -> None:
    original_settings = config_settings.settings
    config_settings.settings = _settings("demo")
    try:
        runner = _runner(tmp_path)
        output = runner.run()
    finally:
        config_settings.settings = original_settings

    assert runner.last_market_provider_name == "MarketDataProvider"
    assert runner.last_news_provider_name == "RSSProvider"
    assert output.learning_summary.total_trades == 0


def test_live_mode_uses_live_providers_but_remains_non_executable(tmp_path: Path) -> None:
    original_settings = config_settings.settings
    config_settings.settings = _settings("live")
    try:
        runner = _LiveRunner(
            memory_engine=MemoryEngine(tmp_path / "memory.json"),
            paper_engine=PaperEngine(),
        )
        output = runner.run()
    finally:
        config_settings.settings = original_settings

    assert runner.last_market_provider_name == "LiveMarketProvider"
    assert runner.last_news_provider_name == "LiveRSSProvider"
    assert output.decision == "NO_DECISION"
    assert output.open_positions == 0
    assert output.learning_summary.total_trades == 0


def test_invalid_mode_raises_runner_error(tmp_path: Path) -> None:
    original_settings = config_settings.settings
    config_settings.settings = _settings("invalid")
    try:
        runner = _runner(tmp_path)
        with __import__("pytest").raises(RunnerError):
            runner.run()
    finally:
        config_settings.settings = original_settings


def test_report_generation_still_works(tmp_path: Path) -> None:
    original_settings = config_settings.settings
    config_settings.settings = _settings("demo")
    try:
        output = _runner(tmp_path).run()
    finally:
        config_settings.settings = original_settings

    assert "Mode: demo." in output.report
    assert "Market provider: MarketDataProvider." in output.report
    assert "News provider: RSSProvider." in output.report


def _runner(tmp_path: Path) -> SharipovAIRunner:
    tmp_path.mkdir(parents=True, exist_ok=True)
    return SharipovAIRunner(
        memory_engine=MemoryEngine(tmp_path / "memory.json"),
        paper_engine=PaperEngine(),
    )


class _LiveRunner(SharipovAIRunner):
    def _create_live_market_provider(self) -> LiveMarketProvider:
        return LiveMarketProvider(client=_FakeBybitClient())

    def _create_live_news_provider(self) -> LiveRSSProvider:
        return LiveRSSProvider(feed_urls=[])


class _FakeBybitClient:
    async def get_tickers(self, category: str = "spot") -> list[TickerInfo]:
        return [
            TickerInfo(
                category=category,
                symbol="BTCUSDT",
                last_price="50000",
                bid_price="49990",
                ask_price="50010",
                price_24h_change_percent="0.03",
                volume_24h="2000",
                turnover_24h="10000000",
            )
        ]


def _settings(run_mode: str) -> AppConfig:
    return AppConfig(
        run_mode=run_mode,
        paper=PaperConfig(initial_balance=10000.0),
        risk=RiskConfig(max_drawdown=10.0, max_position_percent=20.0),
        news=NewsConfig(rss_feeds=[]),
        market=MarketConfig(exchange="bybit", category="spot"),
    )
