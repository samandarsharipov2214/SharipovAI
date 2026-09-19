"""Entry containment regressions: historical price movement is not a forecast."""
from __future__ import annotations

import copy

import pytest

from test_paper_anti_churn_fee_driven import MID, SYMBOL, _build_loop, _plan_buy, _quote


def test_first_buy_without_prospective_edge_waits_without_consuming_or_spending(tmp_path, monkeypatch):
    loop, stream, plan, runtime, clock = _build_loop(tmp_path, monkeypatch)
    _plan_buy(plan, "first-unknown-edge", now_ms=clock.now_ms())
    before = copy.deepcopy(loop._state)
    loop.tick()
    assert loop._state["positions"] == before["positions"] == {}
    assert loop._state["cash"] == before["cash"]
    assert loop._state["total_fees"] == before["total_fees"]
    assert loop._state["trades"] == before["trades"]
    assert runtime.consumed == []
    assert "prospective_edge_unavailable" in loop._state["last_reason"]


@pytest.mark.parametrize("price", [MID - 200, MID + 200])
@pytest.mark.parametrize("reason", ["protective_stop_loss", "protective_take_profit"])
def test_large_move_and_new_id_cannot_replace_unknown_edge(tmp_path, monkeypatch, price, reason):
    loop, stream, plan, runtime, clock = _build_loop(tmp_path, monkeypatch)
    last = {"symbol": SYMBOL, "side": "SELL", "trade_id": "previous-close",
            "decision_id": "previous-hypothesis", "candidate_id": "previous-hypothesis",
            "close_price": MID, "quantity": 0.01, "closed_at_ms": clock.now_ms() - 60_000,
            "reason": reason, "net_pnl": -0.1 if "stop_loss" in reason else 0.2,
            "verified_market_data": True}
    monkeypatch.setattr(loop, "_last_close_for", lambda symbol: last)
    stream.current = _quote(price, now_ms=clock.now_ms())
    _plan_buy(plan, "new-id-same-unproven-hypothesis", now_ms=clock.now_ms())
    loop.tick()
    assert runtime.consumed == []
    assert loop._state["positions"] == {}
    assert "prospective_edge_unavailable" in loop._state["last_reason"]


@pytest.mark.parametrize("edge", [None, float("nan"), float("inf"), True, 1_000_000.0])
def test_invalid_edge_is_unknown_instead_of_falling_back_to_price(tmp_path, monkeypatch, edge):
    loop, stream, plan, runtime, clock = _build_loop(tmp_path, monkeypatch)
    _plan_buy(plan, "invalid-edge", now_ms=clock.now_ms())
    plan["authorization"].expected_edge = edge
    loop.tick()
    assert runtime.consumed == []
    assert "prospective_edge_unavailable" in loop._state["last_reason"]


def test_real_canonical_buy_authorization_still_needs_economic_support(tmp_path, monkeypatch):
    from config.tests.test_council_authorized_paper_loop import _Stream, _RulesService, _proposal
    from autonomous_trading import CanonicalPaperDecisionRuntime, CouncilAuthorizedPaperLoop
    from storage import ProjectDatabase

    monkeypatch.setenv("AUTONOMOUS_PAPER_STATE_FILE", str(tmp_path / "paper.json"))
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'canonical.db'}")
    database.initialize()
    proposal = _proposal(database, "real-canonical-no-forecast", 100.0)
    loop = CouncilAuthorizedPaperLoop(_Stream(100.0), database=database,
        decision_runtime=CanonicalPaperDecisionRuntime(database),
        proposal_provider=lambda *_args: proposal, instrument_rules=_RulesService())
    loop.tick()
    decision = database.get_json("paper_v2_decisions", proposal.decision_id)["value"]
    assert decision["authorized"] is True  # Reaches the actual final BUY gate.
    assert loop._state["positions"] == {}
    assert loop._state["trades"] == []
    assert database.get_json("paper_authorization_consumption", proposal.decision_id) is None
    assert "prospective_edge_unavailable" in loop._state["last_reason"]


@pytest.mark.parametrize("coverage", [-1.0, 0.0, 1.0])
def test_first_entry_must_strictly_exceed_full_cost_cushion(tmp_path, monkeypatch, coverage):
    loop, stream, plan, runtime, clock = _build_loop(tmp_path, monkeypatch)
    _plan_buy(plan, "insufficient-first-edge", now_ms=clock.now_ms())
    cost = loop._estimate_entry_round_trip(SYMBOL, stream.current, None)
    monkeypatch.setattr(loop, "_explicit_expected_edge",
        lambda *args: coverage * cost.all_in * loop.ANTI_CHURN_COST_MARGIN)
    loop.tick()
    assert runtime.consumed == []
    assert "anti_churn_cost_not_covered" in loop._state["last_reason"]


@pytest.mark.parametrize("alias", ["expected_edge", "expected_pnl", "expected_gross_edge", "estimated_edge"])
@pytest.mark.parametrize("location", ["packet", "candidate", "authorization", "assessment"])
def test_unsigned_unversioned_edge_aliases_never_authorize(tmp_path, monkeypatch, alias, location):
    loop, stream, plan, runtime, clock = _build_loop(tmp_path, monkeypatch)
    _plan_buy(plan, "unvalidated-alias", now_ms=clock.now_ms())
    auth = plan["authorization"]
    sources = {"candidate": auth.candidate_result.candidate, "authorization": auth,
               "assessment": auth.assessment, "packet": {alias: 1_000_000.0}}
    if location != "packet":
        setattr(sources[location], alias, 1_000_000.0)
    assert loop._explicit_expected_edge(auth, sources["packet"] if location == "packet" else None) is None
    loop.tick()
    assert not runtime.consumed and not loop._state["positions"]


def test_containment_keeps_collecting_predecision_opinions_for_shadow(tmp_path, monkeypatch):
    from test_paper_economic_observer import Capture
    loop, stream, plan, runtime, clock = _build_loop(tmp_path, monkeypatch)
    loop.economic_observer = Capture()
    _plan_buy(plan, "shadow-despite-wait", now_ms=clock.now_ms())
    loop.tick()
    captured, = loop.economic_observer.rows
    assert captured["council"]["opinions"][0]["action"] == "BUY"
    assert captured["council"]["cost_snapshot_id"] == "cost-1"
    assert captured["quote"]["received_at_unix_ms"] <= captured["decision_time_ms"]
    assert captured["result"]["status"] == "WAIT"
    assert not runtime.consumed and not loop._state["trades"]


@pytest.mark.parametrize("cost", [float("nan"), float("inf"), -1, True, None])
def test_invalid_required_cost_blocks_instead_of_waiting_for_edge(tmp_path, monkeypatch, cost):
    from types import SimpleNamespace
    loop, stream, plan, runtime, clock = _build_loop(tmp_path, monkeypatch)
    _plan_buy(plan, "bad-required-cost", now_ms=clock.now_ms())
    monkeypatch.setattr(loop, "_estimate_entry_round_trip", lambda *args: SimpleNamespace(all_in=cost))
    loop.tick()
    assert loop._state["last_action"] == "BLOCK"
    assert "anti_churn_cost_unavailable" in loop._state["last_reason"]
    assert not runtime.consumed and not loop._state["trades"]


def test_chronological_screen_does_not_use_a_late_persisted_stop():
    from tools.paper_entry_diagnostics import diagnose

    def trade(tid, decision, side, at, price, reason):
        return {"trade_id": tid, "decision_id": decision, "symbol": "ETHUSDT", "side": side,
                "created_at_ms": at, "quantity": 1, "price": price, "fee": 0.1,
                "net_pnl": -1.2 if side == "SELL" else 0, "reason": reason,
                "verified_market_data": True}
    trades = [trade("b1", "d1", "BUY", 1000, 100, "entry"),
              trade("s1", "d1", "SELL", 2000, 99, "protective_stop_loss"),
              trade("b2", "d2", "BUY", 3000, 100, "entry"),
              trade("s2", "d2", "SELL", 4000, 99, "protective_stop_loss")]
    late = diagnose({"trades": trades, "trade_storage_times": {"s1": 3500, "s2": 4500}})
    timely = diagnose({"trades": trades, "trade_storage_times": {"s1": 2500, "s2": 4500}})
    key = "protective_stop_loss:15m"
    assert late["screens"][key]["screened_pairs"] == 0
    assert timely["screens"][key]["screened_pairs"] == 1
    assert late["baseline"]["net_pnl_usdt"] == pytest.approx(-2.4)
    assert late["baseline"]["portfolio_max_drawdown_percent"] is None
    with pytest.raises(ValueError, match="cannot infer availability"):
        diagnose({"trades": trades})
