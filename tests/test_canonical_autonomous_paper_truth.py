from __future__ import annotations

from dataclasses import dataclass

from autonomous_trading.loop import AutonomousPaperLoop
from storage import ProjectDatabase


@dataclass
class _Quote:
    price: float
    change_24h_percent: float | None = 1.0


class _Stream:
    symbols = ("BTCUSDT",)

    def snapshot(self):
        return {
            "status": "live",
            "connected": True,
            "verified": True,
            "age_seconds": 0.1,
            "last_error": "",
            "quotes": {"BTCUSDT": {"price": 120.0}},
        }

    def quote(self, symbol: str):
        assert symbol == "BTCUSDT"
        return _Quote(price=120.0)


def _loop(tmp_path, monkeypatch) -> AutonomousPaperLoop:
    monkeypatch.setenv("AUTONOMOUS_PAPER_STATE_FILE", str(tmp_path / "paper.json"))
    monkeypatch.setenv("AUTONOMOUS_PAPER_WAIT_EVENT_MIN_INTERVAL_SECONDS", "300")
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'project.db'}")
    database.initialize()
    return AutonomousPaperLoop(_Stream(), database=database)


def test_snapshot_is_read_only(tmp_path, monkeypatch) -> None:
    loop = _loop(tmp_path, monkeypatch)
    loop._state["cash"] = 1_000.0
    loop._state["equity"] = 1_000.0
    loop._state["unrealized_pnl"] = 0.0
    loop._state["updated_at"] = "2026-08-04T00:00:00+00:00"
    loop._state["positions"] = {
        "BTCUSDT": {
            "quantity": 1.0,
            "entry_price": 100.0,
            "entry_fee": 0.1,
            "opened_at": "2026-08-04T00:00:00+00:00",
            "reason": "test",
        }
    }
    loop._save_database_state()
    before = loop.database.get_json(loop.state_namespace, loop.scope)

    snapshot = loop.snapshot()
    after = loop.database.get_json(loop.state_namespace, loop.scope)

    assert snapshot["equity"] == 1_120.0
    assert snapshot["unrealized_pnl"] == 20.0
    assert snapshot["mutation_on_read"] is False
    assert loop._state["equity"] == 1_000.0
    assert loop._state["unrealized_pnl"] == 0.0
    assert loop._state["updated_at"] == "2026-08-04T00:00:00+00:00"
    assert after == before


def test_wait_events_are_throttled_per_reason_and_symbol(tmp_path, monkeypatch) -> None:
    loop = _loop(tmp_path, monkeypatch)
    timestamps = iter((1_000_000, 1_001_000, 1_002_000))
    monkeypatch.setattr(loop, "_now_ms", lambda: next(timestamps))

    loop._event("WAIT", "no fresh canonical council proposal", "BTCUSDT")
    loop._event("WAIT", "no fresh canonical council proposal", "BTCUSDT")
    loop._event("WAIT", "different reason", "BTCUSDT")

    assert len(loop.event_history()) == 2
    assert loop._state["suppressed_wait_events"] == 1
    assert [item["reason"] for item in loop._state["events"]] == [
        "no fresh canonical council proposal",
        "different reason",
    ]
