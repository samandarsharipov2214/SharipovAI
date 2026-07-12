from __future__ import annotations

import time

import pytest
from fastapi import FastAPI

from autonomous_trading import (
    AutonomousCouncilProposalProvider,
    CanonicalPaperDecisionRuntime,
    CouncilAuthorizedPaperLoop,
    SharedVerifiedMarketStream,
)
from dashboard.autonomous_trading_api import install_autonomous_trading_api
from dashboard.database_api import install_database_api
from exchange_connector.market_data import MarketDataService, MarketQuote
from exchange_connector.multi_exchange_consensus import ConsensusQuote, MultiExchangeConsensus
from storage import ProjectDatabase
from trading_candidate import TradingDecision


class FakeWorker:
    symbols = ("BTCUSDT",)

    def __init__(self) -> None:
        self.database = None
        self.started = 0
        self.received_at_ms = int(time.time() * 1000)

    def start(self) -> None:
        self.started += 1

    def stop(self) -> None:
        return None

    def quote(self, symbol: str) -> dict[str, object]:
        return {
            "symbol": symbol,
            "price": 60_000.0,
            "exchange_timestamp_ms": self.received_at_ms - 10,
            "received_at_ms": self.received_at_ms,
            "source": "bybit_websocket_v5",
        }

    def status(self) -> dict[str, object]:
        return {
            "connected": True,
            "verified": True,
            "quote_ages_seconds": {"BTCUSDT": 0.01},
            "last_error": None,
            "database_backed": self.database is not None,
        }


class FakeMarketData(MarketDataService):
    def __init__(self) -> None:
        pass

    def quote(self, symbol: str) -> MarketQuote:
        now = int(time.time() * 1000)
        return MarketQuote(
            symbol=symbol,
            price=60_002.0,
            change_24h_percent=2.4,
            volume_24h=250_000_000.0,
            source="bybit",
            source_url="https://api.bybit.com/v5/market/tickers",
            received_at="2026-07-12T00:00:00+00:00",
            received_at_unix_ms=now,
        )


class FakeConsensus(MultiExchangeConsensus):
    def __init__(self) -> None:
        pass

    def quote(self, symbol: str) -> ConsensusQuote:
        return ConsensusQuote(
            symbol=symbol,
            price=60_001.0,
            source_count=4,
            sources=("bybit", "binance", "okx", "kraken"),
            rejected_sources=(),
            rejection_reasons={},
            maximum_deviation_percent=0.03,
            constituents=(
                {"source": "bybit", "price": 60_000.0, "received_at_unix_ms": 1, "deviation_percent": 0.001},
                {"source": "binance", "price": 60_001.0, "received_at_unix_ms": 1, "deviation_percent": 0.0},
                {"source": "okx", "price": 60_002.0, "received_at_unix_ms": 1, "deviation_percent": 0.001},
                {"source": "kraken", "price": 60_001.0, "received_at_unix_ms": 1, "deviation_percent": 0.0},
            ),
        )


def _database(tmp_path) -> ProjectDatabase:
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'canonical-runtime.db'}")
    database.initialize()
    return database


def _positive_news(agent_id: str, *, run_now: bool = False) -> dict[str, object]:
    del run_now
    return {
        "status": "ok",
        "agent": {"id": agent_id, "status": "active", "database_backed": True},
        "memory": [
            {
                "key": f"news-{agent_id}",
                "created_at": int(time.time()),
                "impact": "positive",
                "impact_score": 30.0,
                "credibility_percent": 92.0,
                "needs_confirmation": False,
            }
        ],
    }


def _no_news(agent_id: str, *, run_now: bool = False) -> dict[str, object]:
    del agent_id, run_now
    return {"status": "ok", "agent": {"status": "stale"}, "memory": []}


def _state() -> dict[str, object]:
    return {
        "cash": 10_000.0,
        "equity": 10_000.0,
        "peak_equity": 10_000.0,
        "open_symbols": (),
    }


def test_verified_council_authorization_is_single_use_and_settles_reputation(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("COUNCIL_PROPOSAL_INTERVAL_SECONDS", "10")
    database = _database(tmp_path)
    worker = FakeWorker()
    worker.database = database
    stream = SharedVerifiedMarketStream(
        worker,
        FakeMarketData(),
        FakeConsensus(),
        database=database,
    )
    quote = stream.quote("BTCUSDT")
    provider = AutonomousCouncilProposalProvider(database, stream, news_reader=_positive_news)
    proposal = provider("BTCUSDT", quote, _state())

    assert proposal is not None
    assert proposal.general_controller_decision is TradingDecision.ALLOW
    assert len(proposal.evidence_packet.data_sources) >= 3
    runtime = CanonicalPaperDecisionRuntime(database)
    authorization = runtime.assess_entry(
        proposal.decision_id,
        proposal.agent_payloads,
        proposal.evidence_packet,
        general_controller_decision=proposal.general_controller_decision,
        now_ms=int(time.time() * 1000),
        regime=proposal.regime,
    )
    assert authorization.authorized is True
    runtime.consume_authorization(authorization, consumed_at_ms=int(time.time() * 1000))
    with pytest.raises(Exception, match="already"):
        runtime.consume_authorization(authorization, consumed_at_ms=int(time.time() * 1000))

    settlement = runtime.settle_exit(
        proposal.decision_id,
        net_pnl=25.0,
        drawdown_contribution=0.0,
    )
    duplicate = runtime.settle_exit(
        proposal.decision_id,
        net_pnl=25.0,
        drawdown_contribution=0.0,
    )
    assert settlement == duplicate
    assert settlement["verified_market_data"] is True
    assert database.get_json("paper_decision_settlements", proposal.decision_id) is not None


def test_missing_news_confirmation_cannot_be_upgraded_to_entry(tmp_path) -> None:
    database = _database(tmp_path)
    worker = FakeWorker()
    worker.database = database
    stream = SharedVerifiedMarketStream(worker, FakeMarketData(), FakeConsensus(), database=database)
    provider = AutonomousCouncilProposalProvider(database, stream, news_reader=_no_news)
    proposal = provider("BTCUSDT", stream.quote("BTCUSDT"), _state())

    assert proposal is not None
    assert proposal.general_controller_decision is TradingDecision.WAIT
    authorization = CanonicalPaperDecisionRuntime(database).assess_entry(
        proposal.decision_id,
        proposal.agent_payloads,
        proposal.evidence_packet,
        general_controller_decision=proposal.general_controller_decision,
        now_ms=int(time.time() * 1000),
        regime=proposal.regime,
    )
    assert authorization.authorized is False
    assert authorization.decision is TradingDecision.WAIT


def test_dashboard_installer_uses_one_database_and_canonical_loop(tmp_path) -> None:
    database = _database(tmp_path)
    app = FastAPI()
    install_database_api(app, database=database)
    worker = FakeWorker()
    app.state.bybit_websocket_worker = worker
    app.state.market_data_service = FakeMarketData()
    app.state.multi_exchange_consensus = FakeConsensus()

    install_autonomous_trading_api(app)

    assert worker.database is database
    assert app.state.market_stream.worker is worker
    assert app.state.market_stream.database is database
    assert isinstance(app.state.autonomous_paper_loop, CouncilAuthorizedPaperLoop)
    assert app.state.autonomous_paper_loop.database is database
    assert app.state.canonical_paper_decision_runtime.database is database
    assert app.state.autonomous_paper_loop.snapshot()["entry_without_authorization_allowed"] is False
