from __future__ import annotations

import copy
import time
from threading import Event

import pytest

from autonomous_trading.economic_observer import EconomicOpportunityObserver
from learning_engine.paper_economic_shadow import digest
from storage import ProjectDatabase
from test_paper_economic_shadow import START, opportunity, sources
from test_paper_anti_churn_fee_driven import (
    MID, SYMBOL, _build_loop, _close_long, _open_long, _plan_buy, _quote,
)


class Capture:
    def __init__(self, *, broken=False):
        self.rows = []
        self.failed = 0
        self.broken = broken

    def submit(self, rows):
        if self.broken:
            raise RuntimeError("observer unavailable")
        self.rows.extend(copy.deepcopy(rows))


@pytest.mark.parametrize("broken", [False, True])
@pytest.mark.parametrize("exit_kind", ["council_sell", "stop"])
def test_sequential_financial_behavior_is_identical_with_shadow(tmp_path, monkeypatch, broken, exit_kind):
    outcomes = []
    captures = []
    for mode in ("baseline", "candidate"):
        path = tmp_path / mode
        path.mkdir()
        loop, stream, plan, runtime, clock = _build_loop(path, monkeypatch)
        capture = Capture(broken=broken)
        if mode == "candidate":
            loop.economic_observer = capture
        loop.tick()  # No proposal WAIT must be captured without a stale ID.
        _open_long(loop, stream, plan, clock, "entry")
        _close_long(loop, stream, plan, clock, "exit", authorized=exit_kind == "council_sell")
        clock.advance(15_000)
        stream.current = _quote(MID, now_ms=clock.now_ms())
        _plan_buy(plan, "reentry", now_ms=clock.now_ms())
        loop.tick()
        outcomes.append({
            "account": {k: loop._state[k] for k in ("cash", "equity", "realized_pnl", "total_fees")},
            "fills": [{k: trade.get(k) for k in ("side", "symbol", "price", "quantity", "fee", "net_pnl", "reason")}
                      for trade in reversed(loop.trade_history())],
            "authority_consumed": runtime.consumed,
        })
        captures.append(capture)
    assert outcomes[0] == outcomes[1]
    capture = captures[1]
    if broken:
        assert capture.failed == 4
    else:
        assert len(capture.rows) == 4
        wait, buy, sell, reentry = capture.rows
        assert wait["result"]["status"] == "WAIT" and wait["decision_id"] is None
        assert wait["council"] is None and wait["risk"]["status"] == "NOT_EVALUATED"
        assert buy["decision_id"] == "entry"
        assert buy["decision_quality"]["authorized"] is True
        assert buy["result"]["status"] == "BUY"
        assert sell["result"]["status"] == "SELL"
        assert reentry["proposal_present"] is True
        if exit_kind == "council_sell":
            assert reentry["result"]["phase"] == "anti_churn"


def test_unverified_market_block_and_provider_failure_are_recorded(tmp_path, monkeypatch):
    loop, stream, plan, runtime, clock = _build_loop(tmp_path, monkeypatch)
    capture = Capture()
    loop.economic_observer = capture
    monkeypatch.setattr(stream, "snapshot", lambda: {"verified": False})
    loop.tick()
    assert capture.rows[0]["result"]["status"] == "BLOCK"
    assert capture.rows[0]["quote"] is None
    assert capture.rows[0]["market_verified"] is False
    monkeypatch.setattr(stream, "snapshot", lambda: {"verified": True})
    def fail(*args):
        raise RuntimeError("provider failed")
    loop.proposal_provider = fail
    loop.tick()
    assert capture.rows[1]["result"]["phase"] == "proposal_provider"
    assert runtime.consumed == []


def test_canonical_persistence_is_idempotent_and_does_not_rewrite_history(tmp_path, monkeypatch):
    db = ProjectDatabase(f"sqlite:///{tmp_path / 'observe.db'}")
    db.initialize()
    data = sources()
    monkeypatch.setattr("autonomous_trading.economic_observer.read_sources", lambda *a, **k: data)
    observer = EconomicOpportunityObserver(db)
    early = opportunity(opportunity_id="early", decision_time_ms=START + 2900)
    late = opportunity(opportunity_id="late")
    original = digest(data)
    observer.record_batch([early, late])
    events = db.list_events("paper_economic_opportunities:scope-a", limit=10)
    rows = {event["entity_id"]: event["payload"] for event in events}
    assert rows["early"]["learning_sample_size"] == 0
    assert rows["late"]["learning_sample_size"] == 1
    assert rows["early"]["learning_context_id"] != rows["late"]["learning_context_id"]
    observer.record_batch([early, late])
    assert len(db.list_events("paper_economic_opportunities:scope-a", limit=10)) == 2
    assert observer.recorded == 2
    assert digest(data) == original
    with pytest.raises(ValueError, match="immutable"):
        observer.record_batch([{**late, "regime": "range"}])


def test_future_append_does_not_change_the_original_shadow_input():
    from learning_engine.paper_economic_shadow import assess_opportunity
    data = sources()
    op = opportunity(decision_time_ms=START + 1500)
    prior = assess_opportunity(op, data)
    future = copy.deepcopy(data["trades"][1])
    future["value"]["net_pnl"] = 9999999
    data["trades"].append(future)
    data["outcomes"]["paper:b1"]["value"]["net_pnl"] = 9999999
    assert assess_opportunity(op, data) == prior


def test_slow_writer_is_bounded_nonblocking_and_reports_queue_loss(tmp_path, monkeypatch):
    db = ProjectDatabase(f"sqlite:///{tmp_path / 'queue.db'}")
    db.initialize()
    observer = EconomicOpportunityObserver(db, capacity=1)
    entered, release = Event(), Event()
    def slow(rows):
        entered.set()
        release.wait(3)
        raise ValueError("forced writer failure")
    monkeypatch.setattr(observer, "record_batch", slow)
    observer.submit([opportunity(opportunity_id="one")])
    assert entered.wait(1)
    started = time.monotonic()
    observer.submit([opportunity(opportunity_id="two")])
    observer.submit([opportunity(opportunity_id="three")])
    assert time.monotonic() - started < 0.1
    assert observer.status()["dropped"] == 1
    release.set()
    observer.stop()
    observer._thread.join(2)
    assert not observer._thread.is_alive()
    assert observer.status()["failed"] == 2
    assert observer.status()["error_type"] == "ValueError"
    assert observer.status()["coverage"] == "GAPS_PRESENT"


def test_observer_lifecycle_can_restart_without_losing_queued_work(tmp_path, monkeypatch):
    db = ProjectDatabase(f"sqlite:///{tmp_path / 'restart.db'}")
    db.initialize()
    observer = EconomicOpportunityObserver(db)
    completed = Event()
    monkeypatch.setattr(observer, "record_batch", lambda rows: completed.set())
    for index in range(2):
        completed.clear()
        observer.start()
        observer.submit([opportunity(opportunity_id=str(index))])
        assert completed.wait(1)
        observer.stop()
        observer._thread.join(2)
        assert not observer._thread.is_alive()
    assert observer.dropped == 0
