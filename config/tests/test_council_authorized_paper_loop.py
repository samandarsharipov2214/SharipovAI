from __future__ import annotations

import time
from dataclasses import dataclass, replace
from decimal import Decimal

import pytest

from autonomous_trading import (
    CanonicalPaperDecisionRuntime,
    CouncilAuthorizedPaperLoop,
    CouncilEntryProposal,
)
from autonomous_trading.council_loop import PaperExecutionRejected
from decision_quality import CandidateEvidencePacket
from exchange_connector.bybit_instrument_rules import BybitInstrumentRules
from storage import ProjectDatabase
from trading_core import ExecutionCostModel
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
    bid_price: float | None = None
    ask_price: float | None = None
    volume_24h: float = 100_000_000.0
    received_at_unix_ms: int = 1_000
    source: str = "bybit_websocket_v5"

    def __post_init__(self) -> None:
        if self.bid_price is None:
            self.bid_price = self.price - 0.5
        if self.ask_price is None:
            self.ask_price = self.price + 0.5


class _RulesService:
    def __init__(
        self,
        *,
        qty_step: str = "0.000001",
        min_qty: str = "0.000001",
        min_notional: str = "5",
    ) -> None:
        self.qty_step = Decimal(qty_step)
        self.min_qty = Decimal(min_qty)
        self.min_notional = Decimal(min_notional)

    def get(self, symbol: str, category: str = "spot") -> BybitInstrumentRules:
        return BybitInstrumentRules(
            symbol=symbol,
            category=category,
            status="Trading",
            base_coin=symbol.removesuffix("USDT"),
            quote_coin="USDT",
            tick_size=Decimal("0.1"),
            qty_step=self.qty_step,
            min_qty=self.min_qty,
            min_notional=self.min_notional,
            max_limit_qty=Decimal("1000"),
            max_market_qty=Decimal("1000"),
            min_price=Decimal("0.1"),
            max_price=Decimal("1000000"),
            min_leverage=None,
            max_leverage=None,
            leverage_step=None,
            fetched_at_ms=1,
        )


def _execution_kwargs() -> dict:
    return {
        "instrument_rules": _RulesService(),
        "cost_model": ExecutionCostModel(
            fee_rate=0.001,
            slippage_bps=2.0,
            market_impact_bps=15.0,
        ),
    }


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


def _sell_payloads():
    return [
        {
            "agent_id": "market_intelligence",
            "action": "SELL",
            "confidence": 84,
            "evidence_score": 90,
            "risk_score": 20,
            "evidence_class": "verified_market",
            "verified_market_data": True,
        },
        {
            "agent_id": "news_intelligence",
            "action": "SELL",
            "confidence": 80,
            "evidence_score": 90,
            "risk_score": 20,
            "evidence_class": "verified_market",
            "verified_market_data": True,
        },
        {
            "agent_id": "portfolio_engine",
            "action": "WAIT",
            "confidence": 82,
            "evidence_score": 90,
            "risk_score": 20,
            "evidence_class": "verified_market",
            "verified_market_data": True,
        },
    ]


def _proposal(database: ProjectDatabase, decision_id: str, price: float) -> CouncilEntryProposal:
    now_ms = int(time.time() * 1000)
    portfolio_id = f"portfolio-{decision_id}"
    database.put_json(
        "risk_assessments",
        f"risk-{decision_id}",
        {
            "decision_id": decision_id,
            "risk_score": 20.0,
            "blocks": [],
            "assessment": {
                "allowed_virtual": True,
                "blockers": [],
                "hard_blocks": [],
            },
        },
        expected_version=0,
    )
    database.put_json(
        "portfolio_snapshots",
        portfolio_id,
        {
            "decision_id": decision_id,
            "cash": 10_000.0,
            "equity": 10_000.0,
            "open_symbols": [],
            "environment": "paper",
        },
        expected_version=0,
    )
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
            signal_evidence=("market-signal-1", f"risk-{decision_id}", portfolio_id),
            news_evidence=("news-assessment-1",),
            news_assessment_id="news-assessment-1",
            portfolio_snapshot_id=portfolio_id,
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
        **_execution_kwargs(),
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
    proposal = _proposal(database, "paper-council-1", stream.current.price)
    loop = CouncilAuthorizedPaperLoop(
        stream,
        decision_runtime=CanonicalPaperDecisionRuntime(database),
        proposal_provider=lambda symbol, quote, state: proposal,
        database=database,
        **_execution_kwargs(),
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


def test_spot_sell_signal_does_not_open_short_when_flat(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AUTONOMOUS_PAPER_STATE_FILE", str(tmp_path / "paper.json"))
    database = _database(tmp_path)
    stream = _Stream()
    proposal = _proposal(database, "paper-council-sell-flat", stream.current.price)
    proposal = replace(proposal, agent_payloads=_sell_payloads())
    loop = CouncilAuthorizedPaperLoop(
        stream,
        decision_runtime=CanonicalPaperDecisionRuntime(database),
        proposal_provider=lambda symbol, quote, state: proposal,
        database=database,
        **_execution_kwargs(),
    )

    loop.tick()
    snapshot = loop.snapshot()

    assert snapshot["positions"] == {}
    assert snapshot["trades"] == []
    assert snapshot["last_action"] == "WAIT"

    stored = database.get_json(
        CanonicalPaperDecisionRuntime.v2_decision_namespace,
        "paper-council-sell-flat",
    )
    assert stored is not None
    assert stored["value"]["controller"]["final_intent"] == "SELL"
    assert stored["value"]["execution_authority"] is False


def test_spot_sell_signal_closes_existing_long_with_single_use_authorization(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AUTONOMOUS_PAPER_STATE_FILE", str(tmp_path / "paper.json"))
    database = _database(tmp_path)
    stream = _Stream()
    buy = _proposal(database, "paper-council-buy-long", stream.current.price)
    sell = _proposal(database, "paper-council-sell-long", stream.current.price)
    sell = replace(sell, agent_payloads=_sell_payloads())
    proposals = iter((buy, sell, sell))
    loop = CouncilAuthorizedPaperLoop(
        stream,
        decision_runtime=CanonicalPaperDecisionRuntime(database),
        proposal_provider=lambda _symbol, _quote, _state: next(proposals),
        database=database,
        **_execution_kwargs(),
    )

    loop.tick()
    loop.tick()
    loop.tick()  # retry of the consumed SELL must not mutate PAPER twice.
    snapshot = loop.snapshot()

    assert snapshot["positions"] == {}
    assert [item["side"] for item in snapshot["trades"]] == ["BUY", "SELL"]
    exit_trade = snapshot["trades"][-1]
    assert exit_trade["decision_id"] == "paper-council-buy-long"
    assert exit_trade["exit_authorization_decision_id"] == "paper-council-sell-long"
    assert exit_trade["exit_authorization_single_use"] is True
    assert exit_trade["canonical_exit_protective"] is False

    consumed = database.get_json(
        CanonicalPaperDecisionRuntime.consumption_namespace,
        "paper-council-sell-long",
    )
    assert consumed is not None
    assert consumed["value"]["paper_decision_owner"] == "general_controller_v2"
    assert database.get_json(
        CanonicalPaperDecisionRuntime.settlement_namespace,
        "paper-council-buy-long",
    ) is not None


def test_restart_recovers_a_pending_settlement_once_after_transient_failure(tmp_path, monkeypatch) -> None:
    state_path = tmp_path / "paper.json"
    monkeypatch.setenv("AUTONOMOUS_PAPER_STATE_FILE", str(state_path))
    database = _database(tmp_path)
    stream = _Stream()
    proposal = _proposal(database, "paper-council-settlement-retry", stream.current.price)
    runtime = CanonicalPaperDecisionRuntime(database)
    loop = CouncilAuthorizedPaperLoop(
        stream,
        decision_runtime=runtime,
        proposal_provider=lambda _symbol, _quote, _state: proposal,
        database=database,
        **_execution_kwargs(),
    )

    loop.tick()
    runtime.settle_exit = lambda *_args, **_kwargs: (_ for _ in ()).throw(  # type: ignore[method-assign]
        RuntimeError("transient settlement persistence failure")
    )
    stream.current = _Quote(58_000.0, change_24h_percent=-2.0)
    loop.tick()
    failed = loop.snapshot()
    assert failed["positions"] == {}
    assert failed["trades"][-1]["settlement_retry_pending"] is True
    assert database.get_json(
        CanonicalPaperDecisionRuntime.settlement_namespace,
        "paper-council-settlement-retry",
    ) is None

    recovered = CouncilAuthorizedPaperLoop(
        _Stream(58_000.0),
        decision_runtime=CanonicalPaperDecisionRuntime(database),
        proposal_provider=lambda _symbol, _quote, _state: None,
        database=database,
        **_execution_kwargs(),
    )
    recovered_snapshot = recovered.snapshot()
    recovered_trade = recovered_snapshot["trades"][-1]
    assert recovered_trade.get("settlement_retry_pending") is not True
    assert "decision_settlement_error" not in recovered_trade
    assert recovered_trade["decision_settlement"]["decision_id"] == "paper-council-settlement-retry"
    assert len(recovered_snapshot["trades"]) == 2
    persisted = database.get_json(
        CanonicalPaperDecisionRuntime.settlement_namespace,
        "paper-council-settlement-retry",
    )
    assert persisted is not None

    restarted_again = CouncilAuthorizedPaperLoop(
        _Stream(58_000.0),
        decision_runtime=CanonicalPaperDecisionRuntime(database),
        proposal_provider=lambda _symbol, _quote, _state: None,
        database=database,
        **_execution_kwargs(),
    )
    assert len(restarted_again.snapshot()["trades"]) == 2


def test_protective_stop_loss_does_not_wait_for_new_council(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AUTONOMOUS_PAPER_STATE_FILE", str(tmp_path / "paper.json"))
    database = _database(tmp_path)
    stream = _Stream()
    proposal = _proposal(database, "paper-council-stop", stream.current.price)
    calls = {"count": 0}

    def provider(symbol, quote, state):
        calls["count"] += 1
        return proposal if calls["count"] == 1 else None

    loop = CouncilAuthorizedPaperLoop(
        stream,
        decision_runtime=CanonicalPaperDecisionRuntime(database),
        proposal_provider=provider,
        database=database,
        **_execution_kwargs(),
    )
    loop.tick()
    stream.current = _Quote(58_000.0, change_24h_percent=-2.0)
    loop.tick()
    snapshot = loop.snapshot()

    assert snapshot["positions"] == {}
    assert len(snapshot["trades"]) == 2
    assert snapshot["trades"][-1]["side"] == "SELL"
    assert snapshot["trades"][-1]["reason"] == "protective_stop_loss"


def test_canonical_fills_use_bbo_cost_model_and_verified_decimal_rules(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AUTONOMOUS_PAPER_STATE_FILE", str(tmp_path / "paper.json"))
    database = _database(tmp_path)
    stream = _Stream(100.0)
    stream.current = _Quote(
        100.0,
        bid_price=99.9,
        ask_price=100.1,
        volume_24h=100_000.0,
    )
    buy = _proposal(database, "paper-realistic-buy", 100.0)
    sell = replace(
        _proposal(database, "paper-realistic-sell", 101.0),
        agent_payloads=_sell_payloads(),
    )
    proposals = iter((buy, sell))
    loop = CouncilAuthorizedPaperLoop(
        stream,
        decision_runtime=CanonicalPaperDecisionRuntime(database),
        proposal_provider=lambda *_args: next(proposals),
        database=database,
        instrument_rules=_RulesService(qty_step="0.1", min_qty="0.1"),
        cost_model=ExecutionCostModel(
            fee_rate=0.001,
            slippage_bps=10.0,
            market_impact_bps=15.0,
        ),
    )

    loop.tick()
    entry = loop.snapshot()["trades"][0]
    assert Decimal(str(entry["quantity"])) % Decimal("0.1") == 0
    assert entry["reference_price"] == pytest.approx(100.0)
    assert entry["execution_price"] >= 100.1
    assert entry["price"] == entry["execution_price"]
    assert entry["spread_cost"] > 0
    assert entry["slippage_cost"] > 0
    assert entry["impact_cost"] > 0
    assert entry["fee"] == pytest.approx(
        entry["execution_price"] * entry["quantity"] * entry["fee_rate"]
    )
    assert entry["paper_execution_semantics"] == "bybit_spot_taker_v2"

    stream.current = _Quote(
        101.0,
        bid_price=100.9,
        ask_price=101.1,
        volume_24h=100_000.0,
    )
    loop.tick()
    snapshot = loop.snapshot()
    exit_fill = snapshot["trades"][-1]
    assert exit_fill["execution_price"] <= 100.9
    assert exit_fill["spread_cost"] > 0
    assert exit_fill["slippage_cost"] > 0
    assert exit_fill["fee"] == pytest.approx(
        exit_fill["execution_price"] * exit_fill["quantity"] * exit_fill["fee_rate"]
    )
    expected_net = (
        exit_fill["gross_pnl"]
        - entry["spread_cost"]
        - exit_fill["spread_cost"]
        - entry["slippage_cost"]
        - exit_fill["slippage_cost"]
        - entry["fee"]
        - exit_fill["fee"]
    )
    assert exit_fill["net_pnl"] == pytest.approx(expected_net)
    assert snapshot["equity"] == pytest.approx(10_000.0 + expected_net)
    assert snapshot["realized_pnl"] == pytest.approx(expected_net)
    stored = loop.trade_history()
    assert stored[-2]["execution_price"] == entry["execution_price"]
    assert stored[-1]["net_pnl"] == exit_fill["net_pnl"]


@pytest.mark.parametrize(
    ("rules", "reason"),
    (
        (_RulesService(qty_step="1", min_qty="100"), "quantity is below verified minimum"),
        (_RulesService(min_notional="2000"), "order notional is below verified minimum"),
    ),
)
def test_verified_instrument_minimums_fail_closed_before_authorization_consumption(
    tmp_path,
    monkeypatch,
    rules,
    reason,
) -> None:
    monkeypatch.setenv("AUTONOMOUS_PAPER_STATE_FILE", str(tmp_path / "paper.json"))
    database = _database(tmp_path)
    stream = _Stream(100.0)
    proposal = _proposal(database, f"paper-minimum-{rules.min_qty}-{rules.min_notional}", 100.0)
    loop = CouncilAuthorizedPaperLoop(
        stream,
        decision_runtime=CanonicalPaperDecisionRuntime(database),
        proposal_provider=lambda *_args: proposal,
        database=database,
        instrument_rules=rules,
        cost_model=ExecutionCostModel(),
    )

    loop.tick()

    snapshot = loop.snapshot()
    assert snapshot["positions"] == {}
    assert snapshot["trades"] == []
    assert reason in snapshot["last_reason"]
    assert database.get_json(
        CanonicalPaperDecisionRuntime.consumption_namespace,
        proposal.decision_id,
    ) is None


def test_cash_is_rechecked_before_prepared_fill_mutates_state(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AUTONOMOUS_PAPER_STATE_FILE", str(tmp_path / "paper.json"))
    database = _database(tmp_path)
    stream = _Stream(100.0)
    loop = CouncilAuthorizedPaperLoop(
        stream,
        decision_runtime=CanonicalPaperDecisionRuntime(database),
        proposal_provider=lambda *_args: None,
        database=database,
        **_execution_kwargs(),
    )
    prepared = loop._prepare_open("BTCUSDT", stream.current)
    loop._state["cash"] = 0.0

    with pytest.raises(PaperExecutionRejected, match="cash is insufficient"):
        loop._open("BTCUSDT", stream.current, "test", prepared=prepared)

    assert loop.snapshot()["positions"] == {}
    assert loop.snapshot()["trades"] == []
