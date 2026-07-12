from __future__ import annotations

import time
from dataclasses import dataclass

from autonomous_trading import (
    CanonicalPaperDecisionRuntime,
    CouncilAuthorizedPaperLoop,
    CouncilEntryProposal,
)
from decision_quality import CandidateEvidencePacket
from storage import ProjectDatabase
from trading_candidate import (
    MarketRegime,
    TradingCategory,
    TradingDecision,
    TradingEnvironment,
    TradingSide,
)


@dataclass
class _Quote:
    price: float
    change_24h_percent: float | None = 1.0


class _Stream:
    symbols = ("BTCUSDT",)

    def __init__(self, price: float = 60_000.0) -> None:
        self.current = _Quote(price)

    def snapshot(self):
        return {
            "verified": True,
            "status": "ok",
            "connected": True,
            "age_seconds": 0,
            "last_error": "",
            "quotes": {"BTCUSDT": {"price": self.current.price}},
        }

    def quote(self, symbol: str):
        assert symbol == "BTCUSDT"
        return self.current


def _database(tmp_path) -> ProjectDatabase:
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'council-loop.db'}")
    database.initialize()
    return database


def _payloads():
    return [
        {
            "agent_id": agent,
            "action": "BUY",
            "confidence": confidence,
            "evidence_score": 90,
            "risk_score": 20,
            "evidence_class": "verified_market",
            "verified_market_data": True,
        }
        for agent, confidence in (
            ("market_intelligence", 84),
            ("news_intelligence", 80),
            ("portfolio_engine", 82),
        )
    ]


def _proposal(decision_id: str, price: float) -> CouncilEntryProposal:
    now_ms = int(time.time() * 1000)
    return CouncilEntryProposal(
        decision_id=decision_id,
        agent_payloads=_payloads(),
        general_controller_decision=TradingDecision.ALLOW,
        regime="bull",
        evidence_packet=CandidateEvidencePacket(
            candidate_id=decision_id,
            symbol="BTCUSDT",
            category=TradingCategory.SPOT,
            side=TradingSide.BUY,
            environment=TradingEnvironment.PAPER,
            market_timestamp_ms=now_ms - 100,
            received_timestamp_ms=now_ms - 50,
            reference_price=price,
            data_sources=("bybit_ws", "binance_ws", "coinbase_ws"),
            market_regime=MarketRegime.TREND,
            signal_evidence=("market-signal-1",),
            news_evidence=("news-assessment-1",),
            news_assessment_id="news-assessment-1",
            portfolio_snapshot_id="portfolio-1",
            cost_snapshot_id="cost-1",
            estimated_fees=0.1,
            estimated_slippage=0.05,
            risk_score=20.0,
            risk_blocks=(),
            expires_at_ms=now_ms + 8_000,
        ),
    )


def test_loop_does_not_open_without_council_proposal(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AUTONOMOUS_PAPER_STATE_FILE", str(tmp_path / "paper.json"))
    database = _database(tmp_path)
    stream = _Stream()
    loop = CouncilAuthorizedPaperLoop(
        stream,
        decision_runtime=CanonicalPaperDecisionRuntime(database),
        proposal_provider=lambda symbol, quote, state: None,
        database=database,
    )

    loop.tick()
    snapshot = loop.snapshot()

    assert snapshot["positions"] == {}
    assert snapshot["trades"] == []
    assert snapshot["last_action"] == "WAIT"
    assert snapshot["entry_without_authorization_allowed"] is False


def test_authorized_council_decision_opens_traceable_position(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AUTONOMOUS_PAPER_STATE_FILE", str(tmp_path / "paper.json"))
    database = _database(tmp_path)
    stream = _Stream()
    proposal = _proposal("paper-council-1", stream.current.price)
    loop = CouncilAuthorizedPaperLoop(
        stream,
        decision_runtime=CanonicalPaperDecisionRuntime(database),
        proposal_provider=lambda symbol, quote, state: proposal,
        database=database,
    )

    loop.tick()
    snapshot = loop.snapshot()

    assert "BTCUSDT" in snapshot["positions"]
    assert len(snapshot["trades"]) == 1
    trade = snapshot["trades"][0]
    assert trade["decision_id"] == "paper-council-1"
    assert trade["candidate_id"] == "paper-council-1"
    assert trade["canonical_entry_authorized"] is True
    assert trade["evidence_class"] == "verified_market"
    assert trade["verified_market_data"] is True


def test_protective_stop_loss_does_not_wait_for_new_council(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AUTONOMOUS_PAPER_STATE_FILE", str(tmp_path / "paper.json"))
    database = _database(tmp_path)
    stream = _Stream()
    proposal = _proposal("paper-council-stop", stream.current.price)
    calls = {"count": 0}

    def provider(symbol, quote, state):
        calls["count"] += 1
        return proposal if calls["count"] == 1 else None

    loop = CouncilAuthorizedPaperLoop(
        stream,
        decision_runtime=CanonicalPaperDecisionRuntime(database),
        proposal_provider=provider,
        database=database,
    )
    loop.tick()
    stream.current = _Quote(58_000.0, change_24h_percent=-2.0)
    loop.tick()
    snapshot = loop.snapshot()

    assert snapshot["positions"] == {}
    assert len(snapshot["trades"]) == 2
    assert snapshot["trades"][-1]["side"] == "SELL"
    assert snapshot["trades"][-1]["reason"] == "protective_stop_loss"
