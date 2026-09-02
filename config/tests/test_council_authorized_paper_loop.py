from __future__ import annotations

import random
import sqlite3
import time
from dataclasses import dataclass, replace
from decimal import Decimal
from threading import Thread
from types import SimpleNamespace

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
from trading_core import ExecutionCostModel, Side
from trading_candidate import (
    MarketRegime,
    TradingCategory,
    TradingDecision,
    TradingEnvironment,
    TradingSide,
)


@pytest.fixture(autouse=True)
def _fill_math_uses_large_paper_book(monkeypatch) -> None:
    """These tests size notionals for a 10k book. Production default is 100."""
    monkeypatch.setenv("AUTONOMOUS_PAPER_INITIAL_CASH", "10000")


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
        tick_size: str = "0.1",
        min_qty: str = "0.000001",
        min_notional: str = "5",
        max_market_qty: str | None = "1000",
        source: str = "bybit_v5_instruments_info",
        fetched_at_ms: int = 1,
    ) -> None:
        self.qty_step = Decimal(qty_step)
        self.tick_size = Decimal(tick_size)
        self.min_qty = Decimal(min_qty)
        self.min_notional = Decimal(min_notional)
        self.max_market_qty = (
            None if max_market_qty is None else Decimal(max_market_qty)
        )
        self.source = source
        self.fetched_at_ms = fetched_at_ms
        self.calls = 0

    def get(self, symbol: str, category: str = "spot") -> BybitInstrumentRules:
        self.calls += 1
        return BybitInstrumentRules(
            symbol=symbol,
            category=category,
            status="Trading",
            base_coin=symbol.removesuffix("USDT"),
            quote_coin="USDT",
            tick_size=self.tick_size,
            qty_step=self.qty_step,
            min_qty=self.min_qty,
            min_notional=self.min_notional,
            max_limit_qty=Decimal("1000"),
            max_market_qty=self.max_market_qty,
            min_price=Decimal("0.1"),
            max_price=Decimal("1000000"),
            min_leverage=None,
            max_leverage=None,
            leverage_step=None,
            fetched_at_ms=self.fetched_at_ms,
            source=self.source,
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
    assert entry["impact_cost_included_in_slippage"] is True
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


@pytest.mark.parametrize("cash_mode", ("short_one_unit", "notional_only", "zero", "negative"))
def test_insufficient_cash_boundaries_fail_without_mutation(
    tmp_path,
    monkeypatch,
    cash_mode,
) -> None:
    monkeypatch.setenv("AUTONOMOUS_PAPER_STATE_FILE", str(tmp_path / f"{cash_mode}.json"))
    database = ProjectDatabase(f"sqlite:///{tmp_path / (cash_mode + '.db')}")
    database.initialize()
    stream = _Stream(100.0)
    loop = CouncilAuthorizedPaperLoop(
        stream,
        decision_runtime=CanonicalPaperDecisionRuntime(database),
        proposal_provider=lambda *_args: None,
        database=database,
        **_execution_kwargs(),
    )
    prepared = loop._prepare_open("BTCUSDT", stream.current)
    required = Decimal(str(prepared["notional"])) + Decimal(str(prepared["fee"]))
    values = {
        "short_one_unit": required - Decimal("0.000001"),
        "notional_only": Decimal(str(prepared["notional"])),
        "zero": Decimal("0"),
        "negative": Decimal("-1"),
    }
    loop._state["cash"] = float(values[cash_mode])

    with pytest.raises(PaperExecutionRejected, match="cash is insufficient"):
        loop._open("BTCUSDT", stream.current, "cash_boundary", prepared=prepared)
    assert loop._state["positions"] == {}
    assert loop._state["trades"] == []


def test_exact_cash_for_notional_and_fee_is_accepted_without_rounding_gain(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("AUTONOMOUS_PAPER_STATE_FILE", str(tmp_path / "exact.json"))
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
    required = Decimal(str(prepared["notional"])) + Decimal(str(prepared["fee"]))
    loop._state["cash"] = float(required)

    loop._open("BTCUSDT", stream.current, "cash_boundary", prepared=prepared)

    assert Decimal(str(loop._state["cash"])) == Decimal("0")
    assert len(loop.snapshot()["trades"]) == 1


class _FaultCostModel:
    fee_rate = 0.001
    slippage_bps = 2.0
    market_impact_bps = 15.0
    max_participation_rate = 0.1

    def __init__(self, **overrides) -> None:
        self.overrides = overrides

    def estimate(self, event, *, side, quantity, liquidity_role="taker"):
        reference = event.ask if side.value == "BUY" else event.bid
        defaults = {
            "execution_price": reference * (1.001 if side.value == "BUY" else 0.999),
            "fee_rate": self.fee_rate,
            "participation_rate": 0.001,
            "effective_slippage_bps": 10.0,
        }
        defaults.update(self.overrides)
        return SimpleNamespace(**defaults)


@pytest.mark.parametrize(
    ("side", "execution_price"),
    (("BUY", 99.0), ("SELL", 102.0)),
)
def test_broken_cost_model_cannot_improve_executable_bbo(tmp_path, monkeypatch, side, execution_price) -> None:
    monkeypatch.setenv("AUTONOMOUS_PAPER_STATE_FILE", str(tmp_path / "paper.json"))
    database = _database(tmp_path)
    loop = CouncilAuthorizedPaperLoop(
        _Stream(100.0),
        decision_runtime=CanonicalPaperDecisionRuntime(database),
        proposal_provider=lambda *_args: None,
        database=database,
        instrument_rules=_RulesService(),
        cost_model=_FaultCostModel(execution_price=execution_price),
    )

    with pytest.raises(PaperExecutionRejected, match="executable"):
        if side == "BUY":
            loop._prepare_open("BTCUSDT", loop.stream.current)
        else:
            loop._state["positions"]["BTCUSDT"] = {
                "quantity": 0.1,
                "entry_price": 100.0,
                "entry_fee": 0.0,
            }
            loop._prepare_close("BTCUSDT", loop.stream.current)


@pytest.mark.parametrize(
    ("overrides", "reason"),
    (
        ({"fee_rate": -0.001}, "fee rate"),
        ({"fee_rate": float("nan")}, "fee rate"),
        ({"participation_rate": -0.1}, "participation"),
        ({"participation_rate": 1.1}, "participation"),
        ({"effective_slippage_bps": -1.0}, "slippage"),
        ({"effective_slippage_bps": float("inf")}, "slippage"),
    ),
)
def test_invalid_cost_result_fails_before_state_transition(tmp_path, monkeypatch, overrides, reason) -> None:
    monkeypatch.setenv("AUTONOMOUS_PAPER_STATE_FILE", str(tmp_path / "paper.json"))
    database = _database(tmp_path)
    loop = CouncilAuthorizedPaperLoop(
        _Stream(100.0),
        decision_runtime=CanonicalPaperDecisionRuntime(database),
        proposal_provider=lambda *_args: None,
        database=database,
        instrument_rules=_RulesService(),
        cost_model=_FaultCostModel(**overrides),
    )

    with pytest.raises(PaperExecutionRejected, match=reason):
        loop._prepare_open("BTCUSDT", loop.stream.current)
    assert loop.snapshot()["positions"] == {}
    assert loop.snapshot()["trades"] == []


def test_consumed_authorization_recovers_exactly_once_after_crash_before_fill(
    tmp_path,
    monkeypatch,
) -> None:
    state_path = tmp_path / "paper.json"
    monkeypatch.setenv("AUTONOMOUS_PAPER_STATE_FILE", str(state_path))
    database = _database(tmp_path)
    stream = _Stream(100.0)
    proposal = _proposal(database, "paper-crash-after-consume", 100.0)
    loop = CouncilAuthorizedPaperLoop(
        stream,
        decision_runtime=CanonicalPaperDecisionRuntime(database),
        proposal_provider=lambda *_args: proposal,
        database=database,
        **_execution_kwargs(),
    )
    original_open = loop._open
    loop._open = lambda *_args, **_kwargs: (_ for _ in ()).throw(  # type: ignore[method-assign]
        RuntimeError("simulated crash after authorization consumption")
    )

    with pytest.raises(RuntimeError, match="simulated crash"):
        loop.tick()
    assert database.get_json(
        CanonicalPaperDecisionRuntime.consumption_namespace,
        proposal.decision_id,
    ) is not None
    loop._open = original_open  # type: ignore[method-assign]

    recovered = CouncilAuthorizedPaperLoop(
        stream,
        decision_runtime=CanonicalPaperDecisionRuntime(database),
        proposal_provider=lambda *_args: proposal,
        database=database,
        **_execution_kwargs(),
    )
    snapshot = recovered.snapshot()
    assert list(snapshot["positions"]) == ["BTCUSDT"]
    assert [trade["side"] for trade in snapshot["trades"]] == ["BUY"]
    recovered.tick()
    assert [trade["side"] for trade in recovered.snapshot()["trades"]] == ["BUY"]


def test_legacy_position_without_realistic_metadata_closes_without_rewriting_entry(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("AUTONOMOUS_PAPER_STATE_FILE", str(tmp_path / "paper.json"))
    database = _database(tmp_path)
    stream = _Stream(101.0)
    loop = CouncilAuthorizedPaperLoop(
        stream,
        decision_runtime=CanonicalPaperDecisionRuntime(database),
        proposal_provider=lambda *_args: None,
        database=database,
        instrument_rules=_RulesService(qty_step="0.001", min_qty="0.001"),
        cost_model=ExecutionCostModel(fee_rate=0.001, slippage_bps=2.0, market_impact_bps=0.0),
    )
    legacy_quantity = 1.23456789
    loop._state["cash"] = 9_000.0
    loop._state["positions"]["BTCUSDT"] = {
        "quantity": legacy_quantity,
        "entry_price": 100.0,
        "entry_fee": 0.12,
        "opened_at": "2026-01-01T00:00:00+00:00",
        "decision_id": "legacy-paper-position",
    }

    loop._close("BTCUSDT", stream.current, "protective_take_profit")

    snapshot = loop.snapshot()
    assert snapshot["positions"] == {}
    trade = snapshot["trades"][-1]
    assert trade["quantity"] == legacy_quantity
    assert trade["entry_spread_cost_unknown"] is True
    assert trade["entry_slippage_cost_unknown"] is True
    assert trade["legacy_quantity_rules_exception"] is True


@pytest.mark.parametrize(
    ("bid", "ask"),
    (
        (None, 101.0),
        (99.0, None),
        (0.0, 101.0),
        (99.0, 0.0),
        (-1.0, 101.0),
        (99.0, -1.0),
        (float("nan"), 101.0),
        (99.0, float("nan")),
        (float("inf"), 101.0),
        (99.0, float("inf")),
        ("garbage", 101.0),
        (102.0, 101.0),
    ),
)
def test_malformed_bbo_blocks_before_authorization_consumption(
    tmp_path,
    monkeypatch,
    bid,
    ask,
) -> None:
    monkeypatch.setenv("AUTONOMOUS_PAPER_STATE_FILE", str(tmp_path / "paper.json"))
    database = _database(tmp_path)
    stream = _Stream(100.0)
    stream.current.bid_price = bid
    stream.current.ask_price = ask
    proposal = _proposal(database, "paper-malformed-bbo", 100.0)
    loop = CouncilAuthorizedPaperLoop(
        stream,
        decision_runtime=CanonicalPaperDecisionRuntime(database),
        proposal_provider=lambda *_args: proposal,
        database=database,
        **_execution_kwargs(),
    )

    loop.tick()

    snapshot = loop.snapshot()
    assert snapshot["positions"] == {}
    assert snapshot["trades"] == []
    assert snapshot["last_action"] == "BLOCK"
    assert database.get_json(
        CanonicalPaperDecisionRuntime.consumption_namespace,
        proposal.decision_id,
    ) is None


@pytest.mark.parametrize(
    "rules",
    (
        _RulesService(qty_step="0"),
        _RulesService(qty_step="-0.1"),
        _RulesService(tick_size="0"),
        _RulesService(tick_size="-0.1"),
        _RulesService(min_qty="0"),
        _RulesService(min_notional="0"),
        _RulesService(min_qty="2", max_market_qty="1"),
        _RulesService(source="unverified_cache"),
        _RulesService(fetched_at_ms=0),
    ),
)
def test_malformed_instrument_rules_fail_closed(tmp_path, monkeypatch, rules) -> None:
    monkeypatch.setenv("AUTONOMOUS_PAPER_STATE_FILE", str(tmp_path / "paper.json"))
    database = _database(tmp_path)
    loop = CouncilAuthorizedPaperLoop(
        _Stream(100.0),
        decision_runtime=CanonicalPaperDecisionRuntime(database),
        proposal_provider=lambda *_args: None,
        database=database,
        instrument_rules=rules,
        cost_model=ExecutionCostModel(),
    )

    with pytest.raises(PaperExecutionRejected):
        loop._prepare_open("BTCUSDT", loop.stream.current)


def test_rule_boundaries_are_decimal_and_fail_closed(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AUTONOMOUS_PAPER_STATE_FILE", str(tmp_path / "paper.json"))
    database = _database(tmp_path)
    rules = _RulesService(
        qty_step="0.1",
        tick_size="0.01",
        min_qty="1.0",
        min_notional="100",
        max_market_qty="2.0",
    )
    loop = CouncilAuthorizedPaperLoop(
        _Stream(100.0),
        decision_runtime=CanonicalPaperDecisionRuntime(database),
        proposal_provider=lambda *_args: None,
        database=database,
        instrument_rules=rules,
        cost_model=ExecutionCostModel(fee_rate=0.0, slippage_bps=0.0, market_impact_bps=0.0),
    )

    with pytest.raises(PaperExecutionRejected, match="quantity is below"):
        loop._prepare_execution("BTCUSDT", loop.stream.current, Side.BUY, Decimal("0.999999"))
    exact = loop._prepare_execution("BTCUSDT", loop.stream.current, Side.BUY, Decimal("1.0"))
    above_max = loop._prepare_execution("BTCUSDT", loop.stream.current, Side.BUY, Decimal("2.9"))
    assert Decimal(str(exact["quantity"])) == Decimal("1.0")
    assert Decimal(str(above_max["quantity"])) == Decimal("2.0")
    assert Decimal(str(exact["execution_price"])) % Decimal("0.01") == 0


def _closed_trade_for_costs(
    tmp_path,
    monkeypatch,
    *,
    fee_rate: float,
    slippage_bps: float,
    entry_bid: float,
    entry_ask: float,
    exit_bid: float,
    exit_ask: float,
) -> dict:
    state_file = tmp_path / f"paper-{fee_rate}-{slippage_bps}-{entry_ask}-{exit_bid}.json"
    monkeypatch.setenv("AUTONOMOUS_PAPER_STATE_FILE", str(state_file))
    database = ProjectDatabase(f"sqlite:///{tmp_path / (state_file.stem + '.db')}")
    database.initialize()
    stream = _Stream((entry_bid + entry_ask) / 2)
    stream.current.bid_price = entry_bid
    stream.current.ask_price = entry_ask
    loop = CouncilAuthorizedPaperLoop(
        stream,
        decision_runtime=CanonicalPaperDecisionRuntime(database),
        proposal_provider=lambda *_args: None,
        database=database,
        instrument_rules=_RulesService(qty_step="0.1", tick_size="0.01", min_qty="0.1"),
        cost_model=ExecutionCostModel(
            fee_rate=fee_rate,
            slippage_bps=slippage_bps,
            market_impact_bps=0.0,
        ),
    )
    entry = loop._prepare_execution("BTCUSDT", stream.current, Side.BUY, Decimal("1.0"))
    loop._open("BTCUSDT", stream.current, "property_entry", prepared=entry)
    stream.current = _Quote((exit_bid + exit_ask) / 2, bid_price=exit_bid, ask_price=exit_ask)
    close = loop._prepare_execution("BTCUSDT", stream.current, Side.SELL, Decimal("1.0"))
    loop._close("BTCUSDT", stream.current, "property_exit", prepared=close)
    return loop.snapshot()["trades"][-1]


def test_cost_increases_never_improve_net_pnl_and_zero_cost_matches_baseline(
    tmp_path,
    monkeypatch,
) -> None:
    zero = _closed_trade_for_costs(
        tmp_path,
        monkeypatch,
        fee_rate=0.0,
        slippage_bps=0.0,
        entry_bid=100.0,
        entry_ask=100.0,
        exit_bid=101.0,
        exit_ask=101.0,
    )
    fee = _closed_trade_for_costs(
        tmp_path,
        monkeypatch,
        fee_rate=0.002,
        slippage_bps=0.0,
        entry_bid=100.0,
        entry_ask=100.0,
        exit_bid=101.0,
        exit_ask=101.0,
    )
    spread = _closed_trade_for_costs(
        tmp_path,
        monkeypatch,
        fee_rate=0.0,
        slippage_bps=0.0,
        entry_bid=99.5,
        entry_ask=100.5,
        exit_bid=100.5,
        exit_ask=101.5,
    )
    slippage = _closed_trade_for_costs(
        tmp_path,
        monkeypatch,
        fee_rate=0.0,
        slippage_bps=20.0,
        entry_bid=100.0,
        entry_ask=100.0,
        exit_bid=101.0,
        exit_ask=101.0,
    )
    assert zero["gross_pnl"] == pytest.approx(1.0)
    assert zero["net_pnl"] == pytest.approx(1.0)
    assert fee["net_pnl"] < zero["net_pnl"]
    assert spread["net_pnl"] < zero["net_pnl"]
    assert slippage["net_pnl"] < zero["net_pnl"]


def test_cash_and_pnl_cost_decomposition_reconcile_exactly(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AUTONOMOUS_PAPER_STATE_FILE", str(tmp_path / "paper.json"))
    database = _database(tmp_path)
    stream = _Stream(100.0)
    loop = CouncilAuthorizedPaperLoop(
        stream,
        decision_runtime=CanonicalPaperDecisionRuntime(database),
        proposal_provider=lambda *_args: None,
        database=database,
        instrument_rules=_RulesService(qty_step="0.1", tick_size="0.01", min_qty="0.1"),
        cost_model=ExecutionCostModel(fee_rate=0.001, slippage_bps=10.0, market_impact_bps=5.0),
    )
    cash_before = Decimal(str(loop._state["cash"]))
    entry = loop._prepare_execution("BTCUSDT", stream.current, Side.BUY, Decimal("1.0"))
    loop._open("BTCUSDT", stream.current, "accounting", prepared=entry)
    cash_after_buy = Decimal(str(loop._state["cash"]))
    assert cash_after_buy == cash_before - Decimal(str(entry["notional"])) - Decimal(str(entry["fee"]))

    stream.current = _Quote(101.0)
    exit_fill = loop._prepare_execution("BTCUSDT", stream.current, Side.SELL, Decimal("1.0"))
    loop._close("BTCUSDT", stream.current, "accounting", prepared=exit_fill)
    trade = loop.snapshot()["trades"][-1]
    cash_after_sell = Decimal(str(loop._state["cash"]))
    assert cash_after_sell == cash_after_buy + Decimal(str(exit_fill["notional"])) - Decimal(
        str(exit_fill["fee"])
    )
    decomposed = (
        Decimal(str(trade["gross_pnl"]))
        - Decimal(str(entry["spread_cost"]))
        - Decimal(str(exit_fill["spread_cost"]))
        - Decimal(str(entry["slippage_cost"]))
        - Decimal(str(exit_fill["slippage_cost"]))
        - Decimal(str(entry["fee"]))
        - Decimal(str(exit_fill["fee"]))
    )
    assert Decimal(str(trade["net_pnl"])) == decomposed
    assert Decimal(str(trade["net_pnl"])) == cash_after_sell - cash_before


def test_trade_persistence_failure_rolls_back_memory_then_restart_recovers(
    tmp_path,
    monkeypatch,
) -> None:
    state_path = tmp_path / "paper.json"
    monkeypatch.setenv("AUTONOMOUS_PAPER_STATE_FILE", str(state_path))
    database = _database(tmp_path)
    stream = _Stream(100.0)
    proposal = _proposal(database, "paper-trade-persist-failure", 100.0)
    loop = CouncilAuthorizedPaperLoop(
        stream,
        decision_runtime=CanonicalPaperDecisionRuntime(database),
        proposal_provider=lambda *_args: proposal,
        database=database,
        **_execution_kwargs(),
    )
    original_trade = loop._trade
    loop._trade = lambda *_args, **_kwargs: (_ for _ in ()).throw(  # type: ignore[method-assign]
        sqlite3.OperationalError("simulated trade persistence failure")
    )

    with pytest.raises(sqlite3.OperationalError, match="simulated trade persistence"):
        loop.tick()
    assert loop.snapshot()["positions"] == {}
    assert loop.snapshot()["trades"] == []
    loop._trade = original_trade  # type: ignore[method-assign]

    recovered = CouncilAuthorizedPaperLoop(
        stream,
        decision_runtime=CanonicalPaperDecisionRuntime(database),
        proposal_provider=lambda *_args: proposal,
        database=database,
        **_execution_kwargs(),
    )
    assert len(recovered.snapshot()["trades"]) == 1
    assert list(recovered.snapshot()["positions"]) == ["BTCUSDT"]


def test_restart_after_durable_fill_before_intent_completion_does_not_duplicate(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("AUTONOMOUS_PAPER_STATE_FILE", str(tmp_path / "paper.json"))
    database = _database(tmp_path)
    stream = _Stream(100.0)
    proposal = _proposal(database, "paper-after-durable-fill", 100.0)
    loop = CouncilAuthorizedPaperLoop(
        stream,
        decision_runtime=CanonicalPaperDecisionRuntime(database),
        proposal_provider=lambda *_args: proposal,
        database=database,
        **_execution_kwargs(),
    )
    original_complete = loop._complete_authorized_execution
    loop._complete_authorized_execution = (  # type: ignore[method-assign]
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("simulated crash before intent completion")
        )
    )

    with pytest.raises(RuntimeError, match="before intent completion"):
        loop.tick()
    assert [trade["side"] for trade in loop.snapshot()["trades"]] == ["BUY"]
    loop._complete_authorized_execution = original_complete  # type: ignore[method-assign]

    recovered = CouncilAuthorizedPaperLoop(
        stream,
        decision_runtime=CanonicalPaperDecisionRuntime(database),
        proposal_provider=lambda *_args: proposal,
        database=database,
        **_execution_kwargs(),
    )
    assert [trade["side"] for trade in recovered.snapshot()["trades"]] == ["BUY"]
    assert recovered._state["pending_authorized_executions"] == {}


def test_immutable_trade_insert_failure_recovers_saved_state_without_duplicate(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("AUTONOMOUS_PAPER_STATE_FILE", str(tmp_path / "paper.json"))
    database = _database(tmp_path)
    stream = _Stream(100.0)
    proposal = _proposal(database, "paper-immutable-insert-failure", 100.0)
    loop = CouncilAuthorizedPaperLoop(
        stream,
        decision_runtime=CanonicalPaperDecisionRuntime(database),
        proposal_provider=lambda *_args: proposal,
        database=database,
        **_execution_kwargs(),
    )
    original_put = loop._put_immutable
    failed = False

    def fail_first_trade(namespace, key, value):
        nonlocal failed
        if namespace == loop.trade_namespace and not failed:
            failed = True
            raise sqlite3.OperationalError("simulated immutable trade insert failure")
        return original_put(namespace, key, value)

    loop._put_immutable = fail_first_trade  # type: ignore[method-assign]
    with pytest.raises(sqlite3.OperationalError, match="immutable trade insert"):
        loop.tick()
    assert [trade["side"] for trade in loop.snapshot()["trades"]] == ["BUY"]

    recovered = CouncilAuthorizedPaperLoop(
        stream,
        decision_runtime=CanonicalPaperDecisionRuntime(database),
        proposal_provider=lambda *_args: proposal,
        database=database,
        **_execution_kwargs(),
    )
    assert [trade["side"] for trade in recovered.snapshot()["trades"]] == ["BUY"]
    assert len(recovered.trade_history()) == 1
    assert recovered._state["pending_authorized_executions"] == {}


def test_rules_are_not_fetched_for_wait_ticks_and_pending_state_is_bounded(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("AUTONOMOUS_PAPER_STATE_FILE", str(tmp_path / "paper.json"))
    database = _database(tmp_path)
    rules = _RulesService()
    loop = CouncilAuthorizedPaperLoop(
        _Stream(100.0),
        decision_runtime=CanonicalPaperDecisionRuntime(database),
        proposal_provider=lambda *_args: None,
        database=database,
        instrument_rules=rules,
        cost_model=ExecutionCostModel(),
    )
    for _ in range(500):
        loop.tick()
    assert rules.calls == 0
    assert loop._state["pending_authorized_executions"] == {}
    assert len(loop.snapshot()["events"]) <= 2


def test_seeded_decimal_fuzz_preserves_side_price_and_step_invariants(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AUTONOMOUS_PAPER_STATE_FILE", str(tmp_path / "paper.json"))
    database = _database(tmp_path)
    loop = CouncilAuthorizedPaperLoop(
        _Stream(100.0),
        decision_runtime=CanonicalPaperDecisionRuntime(database),
        proposal_provider=lambda *_args: None,
        database=database,
        instrument_rules=_RulesService(qty_step="0.0001", tick_size="0.0001", min_qty="0.0001"),
        cost_model=ExecutionCostModel(fee_rate=0.001, slippage_bps=3.0, market_impact_bps=0.0),
    )
    rng = random.Random(417)
    for _ in range(40):
        midpoint = Decimal(str(rng.uniform(0.01, 100_000)))
        half_spread = Decimal(str(rng.uniform(0, float(midpoint) * 0.01)))
        bid = midpoint - half_spread
        ask = midpoint + half_spread
        if bid <= 0:
            bid = Decimal("0.0001")
        quote = _Quote(float(midpoint), bid_price=float(bid), ask_price=float(ask))
        quantity = Decimal(str(rng.uniform(0.001, 10)))
        buy = loop._prepare_execution("BTCUSDT", quote, Side.BUY, quantity)
        sell = loop._prepare_execution("BTCUSDT", quote, Side.SELL, quantity)
        assert Decimal(str(buy["execution_price"])) >= ask
        assert Decimal(str(sell["execution_price"])) <= bid
        assert Decimal(str(buy["execution_price"])) % Decimal("0.0001") == 0
        assert Decimal(str(sell["execution_price"])) % Decimal("0.0001") == 0
        assert Decimal(str(buy["quantity"])) % Decimal("0.0001") == 0
        assert buy["fee"] >= 0
        assert sell["fee"] >= 0


def test_cost_model_exception_never_falls_back_to_optimistic_quote(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AUTONOMOUS_PAPER_STATE_FILE", str(tmp_path / "paper.json"))
    database = _database(tmp_path)
    proposal = _proposal(database, "paper-cost-model-failure", 100.0)

    class RaisingCostModel(_FaultCostModel):
        def estimate(self, *_args, **_kwargs):
            raise RuntimeError("simulated cost model failure")

    loop = CouncilAuthorizedPaperLoop(
        _Stream(100.0),
        decision_runtime=CanonicalPaperDecisionRuntime(database),
        proposal_provider=lambda *_args: proposal,
        database=database,
        instrument_rules=_RulesService(),
        cost_model=RaisingCostModel(),
    )

    loop.tick()
    snapshot = loop.snapshot()
    assert snapshot["positions"] == {}
    assert snapshot["trades"] == []
    assert "cost model failure" in snapshot["last_reason"]
    assert database.get_json(
        CanonicalPaperDecisionRuntime.consumption_namespace,
        proposal.decision_id,
    ) is None


def test_authorization_persistence_failure_never_mutates_account_and_can_retry(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("AUTONOMOUS_PAPER_STATE_FILE", str(tmp_path / "paper.json"))
    database = _database(tmp_path)
    proposal = _proposal(database, "paper-consumption-write-failure", 100.0)
    runtime = CanonicalPaperDecisionRuntime(database)
    loop = CouncilAuthorizedPaperLoop(
        _Stream(100.0),
        decision_runtime=runtime,
        proposal_provider=lambda *_args: proposal,
        database=database,
        **_execution_kwargs(),
    )
    original_consume = runtime.consume_authorization
    runtime.consume_authorization = lambda *_args, **_kwargs: (_ for _ in ()).throw(  # type: ignore[method-assign]
        sqlite3.OperationalError("simulated authorization write failure")
    )

    loop.tick()
    assert loop.snapshot()["positions"] == {}
    assert loop.snapshot()["trades"] == []
    assert database.get_json(runtime.consumption_namespace, proposal.decision_id) is None

    runtime.consume_authorization = original_consume  # type: ignore[method-assign]
    loop.tick()
    recovered = loop.snapshot()
    assert len(recovered["trades"]) == 1, recovered["last_reason"]
    assert list(recovered["positions"]) == ["BTCUSDT"]


@pytest.mark.parametrize(
    ("quote", "reason"),
    (
        (_Quote(98.0, change_24h_percent=1.0), "protective_stop_loss"),
        (_Quote(105.0, change_24h_percent=1.0), "protective_take_profit"),
        (_Quote(100.0, change_24h_percent=-1.0), "protective_momentum_exit"),
    ),
)
def test_every_protective_exit_uses_realistic_sell_execution(
    tmp_path,
    monkeypatch,
    quote,
    reason,
) -> None:
    monkeypatch.setenv("AUTONOMOUS_PAPER_STATE_FILE", str(tmp_path / f"{reason}.json"))
    database = ProjectDatabase(f"sqlite:///{tmp_path / (reason + '.db')}")
    database.initialize()
    stream = _Stream(100.0)
    loop = CouncilAuthorizedPaperLoop(
        stream,
        decision_runtime=CanonicalPaperDecisionRuntime(database),
        proposal_provider=lambda *_args: None,
        database=database,
        instrument_rules=_RulesService(qty_step="0.1", min_qty="0.1"),
        cost_model=ExecutionCostModel(fee_rate=0.001, slippage_bps=10.0, market_impact_bps=0.0),
    )
    entry = loop._prepare_execution("BTCUSDT", stream.current, Side.BUY, Decimal("1"))
    loop._open("BTCUSDT", stream.current, "entry", prepared=entry)
    stream.current = quote

    loop._manage_protective_exit("BTCUSDT", quote)

    trade = loop.snapshot()["trades"][-1]
    assert trade["reason"] == reason
    assert trade["execution_price"] <= quote.bid_price
    assert trade["slippage_cost"] > 0
    assert trade["paper_execution_semantics"] == "bybit_spot_taker_v2"


def test_temporary_protective_execution_failure_keeps_position_then_recovers(
    tmp_path,
    monkeypatch,
) -> None:
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
    entry = loop._prepare_execution("BTCUSDT", stream.current, Side.BUY, Decimal("0.1"))
    loop._open("BTCUSDT", stream.current, "entry", prepared=entry)
    bad = _Quote(98.0, change_24h_percent=-2.0)
    bad.bid_price = None

    loop._manage_protective_exit("BTCUSDT", bad)
    assert "BTCUSDT" in loop.snapshot()["positions"]
    assert len(loop.snapshot()["trades"]) == 1

    good = _Quote(98.0, change_24h_percent=-2.0)
    loop._manage_protective_exit("BTCUSDT", good)
    assert loop.snapshot()["positions"] == {}
    assert [trade["side"] for trade in loop.snapshot()["trades"]] == ["BUY", "SELL"]


def test_protective_trade_failure_restores_last_durable_state(tmp_path, monkeypatch) -> None:
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
    entry = loop._prepare_execution("BTCUSDT", stream.current, Side.BUY, Decimal("0.1"))
    loop._open("BTCUSDT", stream.current, "entry", prepared=entry)
    before = loop.snapshot()
    original_trade = loop._trade
    loop._trade = lambda *_args, **_kwargs: (_ for _ in ()).throw(  # type: ignore[method-assign]
        sqlite3.OperationalError("simulated protective trade failure")
    )

    loop._manage_protective_exit("BTCUSDT", _Quote(98.0, change_24h_percent=-2.0))

    after = loop.snapshot()
    assert after["positions"] == before["positions"]
    assert after["cash"] == before["cash"]
    assert after["realized_pnl"] == before["realized_pnl"]
    assert [trade["side"] for trade in after["trades"]] == ["BUY"]
    loop._trade = original_trade  # type: ignore[method-assign]


def test_restart_finishes_settlement_after_durable_protective_close(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("AUTONOMOUS_PAPER_STATE_FILE", str(tmp_path / "paper.json"))
    database = _database(tmp_path)
    stream = _Stream(100.0)
    proposal = _proposal(database, "paper-protective-crash-settlement", 100.0)
    loop = CouncilAuthorizedPaperLoop(
        stream,
        decision_runtime=CanonicalPaperDecisionRuntime(database),
        proposal_provider=lambda *_args: proposal,
        database=database,
        **_execution_kwargs(),
    )
    loop.tick()
    stream.current = _Quote(98.0, change_24h_percent=-2.0)
    loop._settle_or_mark_pending = (  # type: ignore[method-assign]
        lambda *_args, **_kwargs: (_ for _ in ()).throw(SystemExit("simulated process death"))
    )

    with pytest.raises(SystemExit, match="simulated process death"):
        loop._manage_protective_exit("BTCUSDT", stream.current)

    durable = database.get_json(loop.state_namespace, loop.scope)["value"]
    assert list(durable["positions"]) == ["BTCUSDT"]
    assert [trade["side"] for trade in durable["trades"]] == ["BUY"]
    assert len(durable["pending_protective_executions"]) == 1

    recovered = CouncilAuthorizedPaperLoop(
        stream,
        decision_runtime=CanonicalPaperDecisionRuntime(database),
        proposal_provider=lambda *_args: proposal,
        database=database,
        **_execution_kwargs(),
    )
    sell = recovered.snapshot()["trades"][-1]
    assert sell["side"] == "SELL"
    assert "settlement_retry_pending" not in sell
    assert sell["decision_settlement"]["decision_id"] == proposal.decision_id
    assert len(recovered.snapshot()["trades"]) == 2
    assert recovered.snapshot()["pending_protective_executions"] == {}


def test_concurrent_duplicate_ticks_still_create_one_authorized_fill(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AUTONOMOUS_PAPER_STATE_FILE", str(tmp_path / "paper.json"))
    database = _database(tmp_path)
    proposal = _proposal(database, "paper-concurrent-duplicate", 100.0)
    loop = CouncilAuthorizedPaperLoop(
        _Stream(100.0),
        decision_runtime=CanonicalPaperDecisionRuntime(database),
        proposal_provider=lambda *_args: proposal,
        database=database,
        **_execution_kwargs(),
    )
    errors: list[Exception] = []

    def run_tick() -> None:
        try:
            loop.tick()
        except Exception as exc:  # pragma: no cover - assertion records unexpected crash
            errors.append(exc)

    threads = [Thread(target=run_tick) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert not errors
    assert all(not thread.is_alive() for thread in threads)
    assert [trade["side"] for trade in loop.snapshot()["trades"]] == ["BUY"]
    assert database.get_json(
        CanonicalPaperDecisionRuntime.consumption_namespace,
        proposal.decision_id,
    ) is not None
