from __future__ import annotations

import threading
import time
from types import SimpleNamespace

from telegram_runtime_state import canonical_state_from_app, unavailable_state


class FakeLoop:
    def __init__(self, payload):
        self.payload = payload

    def snapshot(self):
        return self.payload


def _app_with(payload):
    return SimpleNamespace(state=SimpleNamespace(autonomous_paper_loop=FakeLoop(payload)))


def test_canonical_state_projects_autonomous_runtime_without_demo_defaults():
    app = _app_with(
        {
            "source_of_truth": "autonomous_paper",
            "mode": "autonomous_paper",
            "equity": 9876.5,
            "cash": 8765.4,
            "realized_pnl": -12.5,
            "unrealized_pnl": 3.25,
            "total_fees": 8.75,
            "positions": {"BTCUSDT": {"quantity": 0.01}},
            "trades": [
                {
                    "symbol": "BTCUSDT",
                    "side": "BUY",
                    "fee": 1.0,
                    "net_pnl": None,
                }
            ],
            "trade_history_count": 17,
            "last_action": "WAIT",
            "last_reason": "council authorization required",
            "worker_running": True,
            "database_backed": True,
            "database_scope": "canonical",
            "mutation_on_read": False,
            "market_stream": {
                "verified": True,
                "age_seconds": 2,
            },
        }
    )

    state = canonical_state_from_app(app)

    assert state["data_available"] is True
    assert state["source_of_truth"] == "autonomous_paper"
    assert state["mode"] == "AUTONOMOUS_PAPER"
    assert state["equity"] == 9876.5
    assert state["cash"] == 8765.4
    assert state["net_pnl"] == -9.25
    assert state["total_fees"] == 8.75
    assert state["open_positions"] == 1
    assert state["trade_count"] == 17
    assert state["worker_running"] is True
    assert state["database_backed"] is True
    assert state["market_verified"] is True
    assert state["mutation_on_read"] is False


def test_missing_runtime_fails_closed_without_fabricated_money():
    app = SimpleNamespace(state=SimpleNamespace())

    state = canonical_state_from_app(app)

    assert state["data_available"] is False
    assert state["source_of_truth"] == "autonomous_paper"
    assert state["mode"] == "UNAVAILABLE"
    assert state["equity"] is None
    assert state["cash"] is None
    assert state["net_pnl"] is None
    assert state["total_fees"] is None
    assert state["open_positions"] is None
    assert state["error"] == "autonomous_paper_loop_missing"


def test_invalid_positions_fail_closed_instead_of_showing_zero_positions():
    app = _app_with(
        {
            "mode": "autonomous_paper",
            "equity": 10000,
            "positions": [],
            "trades": [],
        }
    )

    state = canonical_state_from_app(app)

    assert state["data_available"] is False
    assert state["open_positions"] is None
    assert state["error"] == "autonomous_paper_positions_invalid"


def test_unavailable_state_never_uses_legacy_demo_balance():
    state = unavailable_state("test")

    assert state["equity"] is None
    assert state["cash"] is None
    assert state["mode"] != "PAPER"
    assert state["source_of_truth"] == "autonomous_paper"


def test_canonical_state_does_not_wait_on_held_execution_lock() -> None:
    lock = threading.Lock()
    assert lock.acquire(blocking=False)

    payload = {
        "source_of_truth": "autonomous_paper",
        "mode": "autonomous_paper",
        "equity": 50.0,
        "cash": 50.0,
        "realized_pnl": 0.0,
        "unrealized_pnl": 0.0,
        "total_fees": 0.0,
        "positions": {},
        "trades": [],
        "worker_running": True,
        "database_backed": True,
    }

    def blocking_snapshot():
        raise AssertionError("loop.snapshot() must not be used while the execution lock is held")

    loop = SimpleNamespace(
        _lock=lock,
        _thread=None,
        _last_backup_error="",
        stream=SimpleNamespace(snapshot=lambda: {"verified": False, "status": "idle"}),
        database=SimpleNamespace(get_json=lambda *_args, **_kwargs: {"value": payload}),
        state_namespace="paper_state",
        scope="canonical",
        wait_event_min_interval_seconds=30,
        snapshot=blocking_snapshot,
        trade_history=lambda: [],
        event_history=lambda: [],
    )
    app = SimpleNamespace(state=SimpleNamespace(autonomous_paper_loop=loop))

    started = time.monotonic()
    state = canonical_state_from_app(app)
    assert time.monotonic() - started < 1.0
    assert state["data_available"] is True
    assert state["equity"] == 50.0
    assert state["source_of_truth"] == "autonomous_paper"

