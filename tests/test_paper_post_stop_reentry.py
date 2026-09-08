from __future__ import annotations

import copy

import pytest

from risk_engine.paper_reentry import (
    PAPER_POST_STOP_COOLDOWN_MS,
    PAPER_REENTRY_POLICY_VERSION,
    POST_STOP_BLOCK,
    POST_STOP_EVIDENCE_BLOCK,
    post_stop_reentry_block,
)
from test_paper_anti_churn_fee_driven import (
    MID, SYMBOL, _build_loop, _close_long, _open_long, _plan_buy, _quote,
)


def _stopped_close():
    return {
        "symbol": "BNBUSDT", "side": "SELL", "trade_id": "stopped-bnb",
        "reason": "protective_stop_loss", "net_pnl": -0.16100462,
        "closed_at_ms": 1788874870754, "verified_market_data": True,
    }


def test_bnb_32_minute_reentry_requires_new_risk_epoch():
    close = _stopped_close()
    before = copy.deepcopy(close)
    reason = post_stop_reentry_block(close, symbol="BNBUSDT", now_ms=1788876784682)
    assert reason.startswith(POST_STOP_BLOCK)
    assert "1788961270754" in reason
    assert close == before


@pytest.mark.parametrize("offset,blocked", [(0, True), (60_000, True),
    (PAPER_POST_STOP_COOLDOWN_MS - 1, True), (PAPER_POST_STOP_COOLDOWN_MS, False)])
def test_exact_quarantine_boundary(offset, blocked):
    close = _stopped_close()
    reason = post_stop_reentry_block(close, symbol="BNBUSDT", now_ms=close["closed_at_ms"] + offset)
    assert bool(reason) is blocked


@pytest.mark.parametrize("field,value", [
    ("closed_at_ms", 0), ("closed_at_ms", True), ("closed_at_ms", 1788874870755),
    ("net_pnl", float("nan")), ("net_pnl", None), ("net_pnl", True),
    ("trade_id", ""), ("reason", ""), ("reason", "unverified_exit"),
    ("symbol", "ETHUSDT"), ("side", "BUY"), ("verified_market_data", False),
])
def test_missing_or_inconsistent_close_facts_fail_closed(field, value):
    close = {**_stopped_close(), field: value}
    reason = post_stop_reentry_block(close, symbol="BNBUSDT", now_ms=1788874870754)
    assert reason.startswith(POST_STOP_EVIDENCE_BLOCK)


@pytest.mark.parametrize("reason", ["protective_take_profit", "canonical_council_sell:exit-1", "protective_momentum_exit"])
def test_gate_does_not_invent_stop_from_loss_on_other_exit(reason):
    close = {**_stopped_close(), "reason": reason}
    assert post_stop_reentry_block(close, symbol="BNBUSDT", now_ms=1788874870754) is None
    assert post_stop_reentry_block(None, symbol="ETHUSDT", now_ms=1788874870754) is None


def test_fresh_authorization_large_move_and_edge_cannot_bypass_stop(tmp_path, monkeypatch):
    loop, stream, plan, runtime, clock = _build_loop(tmp_path, monkeypatch, post_stop_policy_mode="enforce")
    _open_long(loop, stream, plan, clock, "entry-1")
    _close_long(loop, stream, plan, clock, "unused", authorized=False)
    stop = loop._state["trades"][-1]
    assert stop["reason"] == "protective_stop_loss"
    cash = loop._state["cash"]
    fees = loop._state["total_fees"]
    clock.advance(32 * 60_000)
    stream.current = _quote(MID + 100, now_ms=clock.now_ms())
    _plan_buy(plan, "new-quote-and-new-candidate", now_ms=clock.now_ms())
    plan["authorization"].expected_edge = 1_000_000
    loop.tick()
    assert not loop._state["positions"]
    assert "new-quote-and-new-candidate" not in runtime.consumed
    assert POST_STOP_BLOCK in loop._state["last_reason"]
    assert loop._state["cash"] == cash
    assert loop._state["total_fees"] == fees
    assert loop._state["trades"][-1] == stop


@pytest.mark.parametrize("legacy", [False, True])
def test_restart_recovers_exact_stop_without_rewriting_financial_history(tmp_path, monkeypatch, legacy):
    loop, stream, plan, runtime, clock = _build_loop(tmp_path, monkeypatch)
    _open_long(loop, stream, plan, clock, "entry-before-restart")
    _close_long(loop, stream, plan, clock, "unused", authorized=False)
    stopped = loop._state["last_close_by_symbol"][SYMBOL]
    immutable = loop.database.get_json(loop.trade_namespace, stopped["trade_id"])
    if legacy:
        for field in ("symbol", "reason", "net_pnl", "verified_market_data"):
            stopped.pop(field)
        loop._persist()
    restarted, stream, plan, runtime, clock = _build_loop(tmp_path, monkeypatch, clock=clock, post_stop_policy_mode="enforce")
    clock.advance(32 * 60_000)
    stream.current = _quote(MID + 100, now_ms=clock.now_ms())
    _plan_buy(plan, "entry-after-restart", now_ms=clock.now_ms())
    restarted.tick()
    assert POST_STOP_BLOCK in restarted._state["last_reason"]
    assert not restarted._state["positions"]
    assert restarted.database.get_json(restarted.trade_namespace, stopped["trade_id"]) == immutable
    assert restarted._last_close_for(SYMBOL)["reason"] == "protective_stop_loss"


@pytest.mark.parametrize("damage", ["missing_trade", "wrong_time", "wrong_symbol", "read_failure"])
def test_legacy_recovery_cannot_replace_missing_lineage(tmp_path, monkeypatch, damage):
    loop, stream, plan, runtime, clock = _build_loop(tmp_path, monkeypatch, post_stop_policy_mode="enforce")
    _open_long(loop, stream, plan, clock, "original-entry")
    _close_long(loop, stream, plan, clock, "unused", authorized=False)
    stopped = loop._state["last_close_by_symbol"][SYMBOL]
    for field in ("symbol", "reason", "net_pnl", "verified_market_data"):
        stopped.pop(field)
    if damage == "missing_trade":
        stopped["trade_id"] = "absent"
    elif damage == "wrong_time":
        stopped["closed_at_ms"] -= 1
    elif damage == "wrong_symbol":
        loop._state["last_close_by_symbol"]["BNBUSDT"] = stopped
    else:
        original = loop.database.get_json
        def fail_close_read(namespace, key):
            if namespace == loop.trade_namespace:
                raise OSError("read unavailable")
            return original(namespace, key)
        monkeypatch.setattr(loop.database, "get_json", fail_close_read)
    symbol = "BNBUSDT" if damage == "wrong_symbol" else SYMBOL
    evidence = loop._last_close_for(symbol)
    assert post_stop_reentry_block(evidence, symbol=symbol, now_ms=clock.now_ms()).startswith(POST_STOP_EVIDENCE_BLOCK)


def test_expiry_preserves_cost_gate_and_new_trade_epoch(tmp_path, monkeypatch):
    monkeypatch.setenv("SHARIPOVAI_BUILD_SHA", "a" * 40)
    loop, stream, plan, runtime, clock = _build_loop(tmp_path, monkeypatch, post_stop_policy_mode="enforce")
    _open_long(loop, stream, plan, clock, "entry-epoch")
    assert loop._state["positions"][SYMBOL]["paper_strategy_version"] == PAPER_REENTRY_POLICY_VERSION + ":enforce"
    _close_long(loop, stream, plan, clock, "unused", authorized=False)
    close = loop._state["last_close_by_symbol"][SYMBOL]
    assert loop._state["trades"][-1]["entry_strategy_version"] == PAPER_REENTRY_POLICY_VERSION + ":enforce"
    clock.ms = close["closed_at_ms"] + PAPER_POST_STOP_COOLDOWN_MS
    stream.current = _quote(close["close_price"], now_ms=clock.now_ms())
    _plan_buy(plan, "expired-but-cost-not-covered", now_ms=clock.now_ms())
    loop.tick()
    assert "anti_churn_cost_not_covered" in loop._state["last_reason"]
    assert not loop._state["positions"]
    _open_long(loop, stream, plan, clock, "fresh-entry", price=MID + 100)
    new = loop._state["trades"][-1]
    assert new["paper_strategy_version"] == PAPER_REENTRY_POLICY_VERSION + ":enforce"
    assert new["paper_build_sha"] == "a" * 40


def test_default_observation_records_would_block_but_preserves_baseline_entry(tmp_path, monkeypatch):
    loop, stream, plan, runtime, clock = _build_loop(tmp_path, monkeypatch)
    assert loop.post_stop_policy_mode == "observe"
    _open_long(loop, stream, plan, clock, "baseline-entry")
    _close_long(loop, stream, plan, clock, "unused", authorized=False)
    stopped = loop._state["trades"][-1]
    clock.advance(32 * 60_000)
    _open_long(loop, stream, plan, clock, "observed-reentry", price=MID + 100)
    trade = loop._state["trades"][-1]
    assessment = trade["post_stop_reentry_assessment"]
    assert assessment["mode"] == "observe"
    assert assessment["would_block"] is True
    assert assessment["last_close_trade_id"] == stopped["trade_id"]
    assert assessment["candidate_decision_id"] == "observed-reentry"
    assert assessment["observed_at_ms"] <= trade["created_at_ms"]
    assert trade["paper_strategy_version"] == PAPER_REENTRY_POLICY_VERSION + ":observe"
    assert "observed-reentry" in runtime.consumed
    stored = loop.database.get_json(loop.trade_namespace, trade["trade_id"])["value"]
    assert stored["post_stop_reentry_assessment"] == assessment


def test_unrecognized_policy_mode_cannot_silently_select_behavior(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="post_stop_policy_mode"):
        _build_loop(tmp_path, monkeypatch, post_stop_policy_mode="live")
