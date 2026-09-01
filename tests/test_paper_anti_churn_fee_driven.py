from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from autonomous_trading.council_loop import CouncilAuthorizedPaperLoop, CouncilEntryProposal
from autonomous_trading.decision_trace import read_decision_trace
from autonomous_trading.market_stream import StreamQuote
from decision_quality import CandidateEvidencePacket
from exchange_connector.bybit_execution import BybitExecutionClient
from exchange_connector.bybit_instrument_rules import BybitInstrumentRules
from exchange_connector.execution_kill_switch import PersistentExecutionKillSwitch
from storage import ProjectDatabase
from trading_candidate import (
    MarketRegime,
    TradingCategory,
    TradingDecision,
    TradingEnvironment,
    TradingSide,
)
from trading_core.costs import ExecutionCostModel
from trading_core.models import MarketEvent


SYMBOL = "ETHUSDT"
MID = 2_500.0
SPREAD = 1.0


class FakeStream:
    symbols = (SYMBOL,)

    def __init__(self, quote: StreamQuote) -> None:
        self.current = quote

    def snapshot(self):
        return {
            "verified": True,
            "status": "live",
            "connected": True,
            "age_seconds": 0,
            "last_error": "",
            "quotes": {self.current.symbol: self.current.to_dict()},
        }

    def quote(self, symbol: str) -> StreamQuote:
        assert symbol == self.current.symbol
        return self.current


class QuietShadow:
    def evaluate(self, **kwargs):
        raise RuntimeError("shadow isolated from anti-churn tests")


class StubRuntime:
    consumption_namespace = "paper_authorization_consumption"

    def __init__(self, database: ProjectDatabase, plan: dict) -> None:
        self.database = database
        self.plan = plan
        self.consumed: list[str] = []

    def assess_entry(self, decision_id, *args, **kwargs):
        del args, kwargs
        return self.plan["authorization"]

    def consume_authorization(self, authorization, *, consumed_at_ms: int):
        self.consumed.append(authorization.decision_id)
        self.database.put_json(
            self.consumption_namespace,
            authorization.decision_id,
            {
                "decision_id": authorization.decision_id,
                "consumed_at_ms": consumed_at_ms,
                "environment": "paper",
                "execution_authority": False,
            },
            expected_version=0,
        )
        return {"consumed": True}

    def settle_exit(self, decision_id, *, net_pnl, drawdown_contribution):
        del drawdown_contribution
        return {
            "decision_id": decision_id,
            "reputation_recorded": False,
            "selected_action": "BUY",
            "net_pnl": net_pnl,
        }

    def status(self):
        return {"paper_only": True, "execution_authority": False}

    def recover_staged_authorization(self, *args, **kwargs):
        raise RuntimeError("staged recovery unused in anti-churn tests")


class StubInstrumentRules:
    def get(self, symbol: str, category: str = "spot") -> BybitInstrumentRules:
        del category
        return BybitInstrumentRules(
            symbol=str(symbol).upper(),
            category="spot",
            status="Trading",
            base_coin="ETH",
            quote_coin="USDT",
            tick_size=Decimal("0.01"),
            qty_step=Decimal("0.0001"),
            min_qty=Decimal("0.0001"),
            min_notional=Decimal("5"),
            max_limit_qty=Decimal("1000"),
            max_market_qty=Decimal("500"),
            min_price=Decimal("0.01"),
            max_price=Decimal("1000000"),
            min_leverage=None,
            max_leverage=None,
            leverage_step=None,
            fetched_at_ms=1_700_000_000_000,
            source="bybit_v5_instruments_info",
        )


def _quote(price: float, *, now_ms: int, spread: float = SPREAD) -> StreamQuote:
    half = spread / 2.0
    return StreamQuote(
        symbol=SYMBOL,
        price=price,
        change_24h_percent=1.0,
        volume_24h=250_000_000.0,
        source="bybit_websocket_v5",
        received_at="2026-09-01T00:00:00+00:00",
        received_at_unix_ms=now_ms,
        verified=True,
        bid_price=price - half,
        ask_price=price + half,
    )


def _packet(decision_id: str, *, now_ms: int, estimated_fees: float = 0.1, estimated_slippage: float = 0.05):
    return CandidateEvidencePacket(
        candidate_id=decision_id,
        symbol=SYMBOL,
        category=TradingCategory.SPOT,
        side=TradingSide.BUY,
        environment=TradingEnvironment.PAPER,
        market_timestamp_ms=now_ms - 200,
        received_timestamp_ms=now_ms - 100,
        reference_price=MID,
        data_sources=("bybit", "bitget", "mexc"),
        market_regime=MarketRegime.TREND,
        signal_evidence=("market-evidence",),
        news_evidence=("news-1",),
        news_assessment_id="news-assessment-1",
        portfolio_snapshot_id="portfolio-1",
        cost_snapshot_id="cost-1",
        estimated_fees=estimated_fees,
        estimated_slippage=estimated_slippage,
        risk_score=20.0,
        risk_blocks=(),
        expires_at_ms=now_ms + 8_000,
    )


def _authorization(decision_id: str, *, side: TradingSide, now_ms: int):
    return SimpleNamespace(
        decision_id=decision_id,
        authorized=True,
        decision=TradingDecision.ALLOW,
        reason="canonical paper authorization",
        candidate_result=SimpleNamespace(
            candidate=SimpleNamespace(
                candidate_id=decision_id,
                symbol=SYMBOL,
                side=side,
                market_timestamp_ms=now_ms - 200,
            ),
            validation=SimpleNamespace(valid=True, errors=()),
            general_controller_decision=TradingDecision.ALLOW,
        ),
        assessment=SimpleNamespace(
            blocked=False,
            quality_score=90.0,
            agreement=90.0,
            confidence=90.0,
            action="ALLOW",
            reason="verified evidence",
            regime="trend",
        ),
    )


def _plan_buy(plan: dict, decision_id: str, *, now_ms: int) -> None:
    packet = _packet(decision_id, now_ms=now_ms)
    authorization = _authorization(decision_id, side=TradingSide.BUY, now_ms=now_ms)
    plan["authorization"] = authorization
    plan["proposal"] = CouncilEntryProposal(
        decision_id=decision_id,
        agent_payloads=(
            {
                "agent_id": "technical_analyst",
                "action": "BUY",
                "confidence": 90,
                "evidence_score": 90,
                "risk_score": 20,
                "verified_market_data": True,
            },
        ),
        evidence_packet=packet,
        general_controller_decision=TradingDecision.ALLOW,
        regime="trend",
    )


def _plan_sell(plan: dict, decision_id: str, *, now_ms: int) -> None:
    packet = _packet(decision_id, now_ms=now_ms)
    authorization = _authorization(decision_id, side=TradingSide.SELL, now_ms=now_ms)
    plan["authorization"] = authorization
    plan["proposal"] = CouncilEntryProposal(
        decision_id=decision_id,
        agent_payloads=(
            {
                "agent_id": "technical_analyst",
                "action": "SELL",
                "confidence": 90,
                "evidence_score": 90,
                "risk_score": 20,
                "verified_market_data": True,
            },
        ),
        evidence_packet=packet,
        general_controller_decision=TradingDecision.ALLOW,
        regime="trend",
    )


class Clock:
    def __init__(self, start_ms: int = 1_700_000_000_000) -> None:
        self.ms = start_ms

    def now_ms(self) -> int:
        return self.ms

    def advance(self, ms: int) -> int:
        self.ms += ms
        return self.ms


def _build_loop(tmp_path, monkeypatch, *, clock: Clock | None = None):
    monkeypatch.setenv("AUTONOMOUS_PAPER_STATE_FILE", str(tmp_path / "paper.json"))
    monkeypatch.setenv("AUTONOMOUS_PAPER_MAX_POSITION_PERCENT", "10")
    monkeypatch.setenv("EXCHANGE_DEFAULT_FEE_RATE", "0.001")
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'project.db'}")
    database.initialize()
    clock = clock or Clock()
    stream = FakeStream(_quote(MID, now_ms=clock.now_ms()))
    plan: dict = {}
    runtime = StubRuntime(database, plan)

    def provider(symbol, quote, state):
        del symbol, quote, state
        return plan.get("proposal")

    loop = CouncilAuthorizedPaperLoop(
        stream,
        decision_runtime=runtime,  # type: ignore[arg-type]
        proposal_provider=provider,
        database=database,
        shadow_runtime=QuietShadow(),  # type: ignore[arg-type]
        instrument_rules=StubInstrumentRules(),  # type: ignore[arg-type]
        cost_model=ExecutionCostModel(fee_rate=0.001, slippage_bps=2.0, market_impact_bps=15.0),
    )
    loop._now_ms = clock.now_ms  # type: ignore[method-assign]
    return loop, stream, plan, runtime, clock


def _open_long(loop, stream, plan, clock, decision_id: str, *, price: float = MID) -> None:
    clock.advance(1_000)
    stream.current = _quote(price, now_ms=clock.now_ms())
    _plan_buy(plan, decision_id, now_ms=clock.now_ms())
    consumed_before = list(loop.decision_runtime.consumed)
    loop.tick()
    assert SYMBOL in loop._state["positions"]
    assert decision_id in loop.decision_runtime.consumed
    assert loop.decision_runtime.consumed[-1] == decision_id
    assert loop.decision_runtime.consumed != consumed_before


def _close_long(loop, stream, plan, clock, decision_id: str, *, price: float = MID, authorized: bool = True) -> None:
    clock.advance(1_000)
    stream.current = _quote(price, now_ms=clock.now_ms())
    if authorized:
        _plan_sell(plan, decision_id, now_ms=clock.now_ms())
        loop.tick()
    else:
        stream.current = _quote(price * 0.97, now_ms=clock.now_ms())
        loop.tick()
    assert SYMBOL not in loop._state["positions"]
    last_close = loop._state["last_close_by_symbol"][SYMBOL]
    assert last_close["close_price"] > 0
    assert last_close["side"] == "SELL"
    assert last_close["trade_id"]


def test_a_fast_round_trip_blocks_immediate_reentry(tmp_path, monkeypatch) -> None:
    clock = Clock()
    loop, stream, plan, runtime, clock = _build_loop(tmp_path, monkeypatch, clock=clock)
    _open_long(loop, stream, plan, clock, "eth-buy-1")
    _close_long(loop, stream, plan, clock, "eth-sell-1")
    clock.advance(15_000)
    stream.current = _quote(MID, now_ms=clock.now_ms())
    _plan_buy(plan, "eth-buy-2", now_ms=clock.now_ms())
    loop.tick()

    assert SYMBOL not in loop._state["positions"]
    assert "eth-buy-2" not in runtime.consumed
    assert loop._state["last_action"] == "WAIT"
    assert "anti_churn_cost_not_covered" in loop._state["last_reason"]
    trace = read_decision_trace(loop.database, SYMBOL)
    assert trace is not None
    assert "anti_churn_cost_not_covered" in str(trace.get("reason") or "")
    events = [item for item in loop.event_history() if "anti_churn" in str(item.get("reason") or "")]
    assert events


def test_b_same_decision_candidate_after_close_blocked(tmp_path, monkeypatch) -> None:
    loop, stream, plan, runtime, clock = _build_loop(tmp_path, monkeypatch)
    _open_long(loop, stream, plan, clock, "eth-buy-same")
    _close_long(loop, stream, plan, clock, "eth-sell-same")
    # Even a large move is still the same BUY identity.
    clock.advance(2_000)
    stream.current = _quote(MID - 80.0, now_ms=clock.now_ms())
    _plan_buy(plan, "eth-buy-same", now_ms=clock.now_ms())
    loop.tick()

    assert SYMBOL not in loop._state["positions"]
    assert runtime.consumed.count("eth-buy-same") == 1
    assert "anti_churn_reentry" in loop._state["last_reason"]


def test_c_market_not_moved_enough_to_cover_costs(tmp_path, monkeypatch) -> None:
    loop, stream, plan, runtime, clock = _build_loop(tmp_path, monkeypatch)
    _open_long(loop, stream, plan, clock, "eth-buy-c1")
    _close_long(loop, stream, plan, clock, "eth-sell-c1")
    clock.advance(2_000)
    stream.current = _quote(MID, now_ms=clock.now_ms())
    _plan_buy(plan, "eth-buy-c2", now_ms=clock.now_ms())
    reason = loop._anti_churn_buy_block_reason(
        SYMBOL,
        stream.current,
        plan["authorization"],
        proposal=plan["proposal"],
    )
    loop.tick()

    assert reason is not None
    assert reason.startswith("anti_churn_cost_not_covered")
    assert "anti_churn_cost_not_covered" in loop._state["last_reason"]
    assert "eth-buy-c2" not in runtime.consumed
    assert SYMBOL not in loop._state["positions"]


def test_d_new_evidence_and_sufficient_price_move_may_pass(tmp_path, monkeypatch) -> None:
    loop, stream, plan, runtime, clock = _build_loop(tmp_path, monkeypatch)
    _open_long(loop, stream, plan, clock, "eth-buy-d1")
    _close_long(loop, stream, plan, clock, "eth-sell-d1")
    clock.advance(2_000)
    favorable = MID - 80.0
    stream.current = _quote(favorable, now_ms=clock.now_ms())
    _plan_buy(plan, "eth-buy-d2", now_ms=clock.now_ms())
    helper_reason = loop._anti_churn_buy_block_reason(
        SYMBOL,
        stream.current,
        plan["authorization"],
        proposal=plan["proposal"],
    )
    loop.tick()

    assert helper_reason is None
    assert SYMBOL in loop._state["positions"]
    assert "eth-buy-d2" in runtime.consumed


def test_e_protective_exit_is_never_delayed_by_anti_churn(tmp_path, monkeypatch) -> None:
    loop, stream, plan, runtime, clock = _build_loop(tmp_path, monkeypatch)
    _open_long(loop, stream, plan, clock, "eth-buy-e1")
    loop._state["last_close_by_symbol"][SYMBOL] = {
        "closed_at_ms": clock.now_ms(),
        "close_price": MID,
        "decision_id": "eth-buy-e1",
        "candidate_id": "eth-buy-e1",
        "fees": 5.0,
        "spread_cost": 1.0,
        "slippage_cost": 1.0,
        "side": "SELL",
        "trade_id": "seed",
        "quantity": 0.4,
    }
    stop_quote = _quote(MID * 0.97, now_ms=clock.now_ms())
    stream.current = stop_quote
    plan["proposal"] = None
    before_consumed = list(runtime.consumed)
    loop._manage_protective_exit(SYMBOL, stop_quote)

    assert SYMBOL not in loop._state["positions"]
    assert runtime.consumed == before_consumed
    assert loop._state["last_action"] == "SELL"
    assert "protective_stop_loss" in loop._state["last_reason"]
    assert "anti_churn" not in loop._state["last_reason"]


def test_f_canonical_authorized_sell_closes_existing_long(tmp_path, monkeypatch) -> None:
    loop, stream, plan, runtime, clock = _build_loop(tmp_path, monkeypatch)
    _open_long(loop, stream, plan, clock, "eth-buy-f1")
    # Turnover evidence must not delay an authorized SELL of an existing long.
    now = clock.now_ms()
    loop._state["trades"].extend(
        {
            "trade_id": f"seed-sell-{index}",
            "created_at_ms": now - 1_000,
            "symbol": SYMBOL,
            "side": "SELL",
            "fee": 1.0,
        }
        for index in range(3)
    )
    _close_long(loop, stream, plan, clock, "eth-sell-f1")
    assert "eth-sell-f1" in runtime.consumed
    assert any(
        item.get("side") == "SELL" and "canonical_council_sell" in str(item.get("reason") or "")
        for item in loop._state["trades"]
    )


def test_g_restart_persists_last_close_and_still_blocks_churn(tmp_path, monkeypatch) -> None:
    clock = Clock()
    loop, stream, plan, runtime, clock = _build_loop(tmp_path, monkeypatch, clock=clock)
    _open_long(loop, stream, plan, clock, "eth-buy-g1")
    _close_long(loop, stream, plan, clock, "eth-sell-g1")
    persisted = dict(loop._state["last_close_by_symbol"][SYMBOL])
    dsn = loop.database.dsn
    state_file = str(tmp_path / "paper.json")

    database = ProjectDatabase(dsn)
    database.initialize()
    restarted_plan: dict = {}
    restarted_runtime = StubRuntime(database, restarted_plan)
    restarted_stream = FakeStream(_quote(MID, now_ms=clock.now_ms()))

    def provider(symbol, quote, state):
        del symbol, quote, state
        return restarted_plan.get("proposal")

    monkeypatch.setenv("AUTONOMOUS_PAPER_STATE_FILE", state_file)
    restarted = CouncilAuthorizedPaperLoop(
        restarted_stream,
        decision_runtime=restarted_runtime,  # type: ignore[arg-type]
        proposal_provider=provider,
        database=database,
        shadow_runtime=QuietShadow(),  # type: ignore[arg-type]
        instrument_rules=StubInstrumentRules(),  # type: ignore[arg-type]
        cost_model=ExecutionCostModel(fee_rate=0.001),
    )
    restarted._now_ms = clock.now_ms  # type: ignore[method-assign]
    assert restarted._state["last_close_by_symbol"][SYMBOL]["close_price"] == persisted["close_price"]
    assert restarted._state["last_close_by_symbol"][SYMBOL]["decision_id"] == "eth-buy-g1"

    _plan_buy(restarted_plan, "eth-buy-g2", now_ms=clock.now_ms())
    restarted.tick()
    assert SYMBOL not in restarted._state["positions"]
    assert "eth-buy-g2" not in restarted_runtime.consumed
    assert "anti_churn_" in restarted._state["last_reason"]


def test_h_fees_spread_slippage_all_participate_in_cost_gate(tmp_path, monkeypatch) -> None:
    event = MarketEvent(
        timestamp_ms=1,
        symbol=SYMBOL,
        bid=MID - 0.5,
        ask=MID + 0.5,
        source="fixture",
        volume=100_000.0,
    )
    base = ExecutionCostModel(fee_rate=0.001, slippage_bps=2.0, market_impact_bps=0.0)
    fat_fee = ExecutionCostModel(fee_rate=0.01, slippage_bps=2.0, market_impact_bps=0.0)
    fat_slip = ExecutionCostModel(fee_rate=0.001, slippage_bps=50.0, market_impact_bps=0.0)
    wide = MarketEvent(
        timestamp_ms=1,
        symbol=SYMBOL,
        bid=MID - 5.0,
        ask=MID + 5.0,
        source="fixture",
        volume=100_000.0,
    )
    qty = 0.4
    base_rt = base.estimate_round_trip(event, quantity=qty)
    fee_rt = fat_fee.estimate_round_trip(event, quantity=qty)
    slip_rt = fat_slip.estimate_round_trip(event, quantity=qty)
    spread_rt = base.estimate_round_trip(wide, quantity=qty)

    assert base_rt.fee > 0
    assert base_rt.spread_cost > 0
    assert base_rt.slippage_cost > 0
    assert base_rt.all_in == base_rt.fee + base_rt.spread_cost + base_rt.slippage_cost
    assert fee_rt.fee > base_rt.fee
    assert fee_rt.all_in > base_rt.all_in
    assert slip_rt.slippage_cost > base_rt.slippage_cost
    assert slip_rt.all_in > base_rt.all_in
    assert spread_rt.spread_cost > base_rt.spread_cost
    assert spread_rt.all_in > base_rt.all_in

    loop, stream, plan, _runtime, clock = _build_loop(tmp_path, monkeypatch)
    _open_long(loop, stream, plan, clock, "eth-buy-h1")
    _close_long(loop, stream, plan, clock, "eth-sell-h1")
    _plan_buy(plan, "eth-buy-h2", now_ms=clock.now_ms())
    reason = loop._anti_churn_buy_block_reason(
        SYMBOL,
        stream.current,
        plan["authorization"],
        proposal=plan["proposal"],
    )
    assert reason is not None
    assert "anti_churn_cost_not_covered" in reason
    assert "fees+spread+slippage" in reason


def test_i_no_short_positions_introduced(tmp_path, monkeypatch) -> None:
    loop, stream, plan, runtime, clock = _build_loop(tmp_path, monkeypatch)
    clock.advance(1_000)
    stream.current = _quote(MID, now_ms=clock.now_ms())
    _plan_sell(plan, "eth-short-1", now_ms=clock.now_ms())
    loop.tick()

    assert loop._state["positions"] == {}
    assert "eth-short-1" not in runtime.consumed
    assert "does not open a short position" in loop._state["last_reason"]
    assert all(float(item.get("quantity") or 0) >= 0 for item in loop._state["trades"])


def test_j_real_execution_remains_impossible(tmp_path, monkeypatch) -> None:
    before_kill = os.getenv("EXECUTION_KILL_SWITCH")
    calls: list[tuple] = []

    def forbidden_execute(self, *args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("BybitExecutionClient.execute must not run on the paper path")

    monkeypatch.setattr(BybitExecutionClient, "execute", forbidden_execute)
    loop, stream, plan, runtime, clock = _build_loop(tmp_path, monkeypatch)
    _open_long(loop, stream, plan, clock, "eth-buy-j1")
    _close_long(loop, stream, plan, clock, "eth-sell-j1")
    snapshot = loop.snapshot()

    assert calls == []
    assert snapshot["real_execution_enabled"] is False
    assert os.getenv("EXECUTION_KILL_SWITCH") == before_kill
    assert os.getenv("EXECUTION_KILL_SWITCH", "1").strip() != "0"
    switch = PersistentExecutionKillSwitch(loop.database).state()
    assert switch.active is True
    source = Path(__file__).resolve().parents[1] / "autonomous_trading" / "council_loop.py"
    assert "BybitExecutionClient" not in source.read_text(encoding="utf-8")


def test_turnover_limit_blocks_new_buy(tmp_path, monkeypatch) -> None:
    loop, stream, plan, runtime, clock = _build_loop(tmp_path, monkeypatch)
    now = clock.now_ms()
    loop._state["trades"] = [
        {
            "trade_id": f"seed-{index}",
            "created_at_ms": now - 1_000,
            "symbol": SYMBOL,
            "side": "SELL",
            "fee": 1.0,
            "price": MID,
            "quantity": 0.4,
        }
        for index in range(3)
    ]
    loop._state["last_close_by_symbol"][SYMBOL] = {
        "closed_at_ms": now,
        "close_price": MID,
        "decision_id": "old",
        "candidate_id": "old",
        "fees": 3.0,
        "spread_cost": 1.0,
        "slippage_cost": 1.0,
        "side": "SELL",
        "trade_id": "seed-2",
        "quantity": 0.4,
    }
    stream.current = _quote(MID - 80.0, now_ms=now)
    _plan_buy(plan, "eth-buy-turn", now_ms=now)
    loop.tick()

    assert SYMBOL not in loop._state["positions"]
    assert "eth-buy-turn" not in runtime.consumed
    assert loop._state["last_action"] == "BLOCK"
    assert "anti_churn_turnover_limit" in loop._state["last_reason"]

