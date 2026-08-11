from __future__ import annotations

import hashlib
from pathlib import Path

import telegram_system_adapter
from canonical_surface_state import load_canonical_paper_state
from storage import ProjectDatabase


def _scope(path: Path) -> str:
    return hashlib.sha256(str(path.expanduser().resolve()).encode("utf-8")).hexdigest()[:20]


def test_surface_projection_reads_canonical_state_and_full_trade_history(tmp_path, monkeypatch) -> None:
    state_file = tmp_path / "paper.json"
    monkeypatch.setenv("AUTONOMOUS_PAPER_STATE_FILE", str(state_file))
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'surface.db'}")
    database.initialize()
    scope = _scope(state_file)
    database.put_json(
        "autonomous_paper_state",
        scope,
        {
            "cash": 9_900.0,
            "equity": 10_025.0,
            "realized_pnl": 20.0,
            "unrealized_pnl": 5.0,
            "total_fees": 1.5,
            "positions": {"BTCUSDT": {"quantity": 0.01, "entry_price": 50_000.0}},
            "trades": [],
        },
        expected_version=0,
    )
    database.put_json(
        f"paper_trades:{scope}",
        "trade-1",
        {
            "trade_id": "trade-1",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "time": "2026-08-11T10:00:00+00:00",
            "fee": 1.5,
            "net_pnl": None,
        },
        expected_version=0,
    )

    state = load_canonical_paper_state(database)

    assert state["status"] == "ok"
    assert state["source_of_truth"] == "ProjectDatabase/CouncilAuthorizedPaperLoop"
    assert state["net_pnl"] == 25.0
    assert state["open_positions"] == 1
    assert state["trade_history_count"] == 1
    assert state["trades"][0]["trade_id"] == "trade-1"


def test_missing_canonical_state_does_not_fall_back_to_demo(tmp_path, monkeypatch) -> None:
    state_file = tmp_path / "missing-paper.json"
    monkeypatch.setenv("AUTONOMOUS_PAPER_STATE_FILE", str(state_file))
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'empty.db'}")
    database.initialize()

    state = load_canonical_paper_state(database)

    assert state["status"] == "unavailable"
    assert state["trades"] == []
    assert state["real_orders_blocked"] is True


def test_telegram_imports_canonical_surface_reader() -> None:
    assert telegram_system_adapter.load_shared_state is load_canonical_paper_state


def test_telegram_trade_text_includes_canonical_timestamp(monkeypatch) -> None:
    monkeypatch.setattr(
        telegram_system_adapter,
        "load_shared_state",
        lambda: {
            "status": "ok",
            "source_of_truth": "ProjectDatabase/CouncilAuthorizedPaperLoop",
            "trades": [
                {
                    "trade_id": "trade-1",
                    "symbol": "BTCUSDT",
                    "side": "BUY",
                    "time": "2026-08-11T10:00:00+00:00",
                    "fee": 1.0,
                    "net_pnl": None,
                }
            ],
        },
    )

    text = telegram_system_adapter._trades()

    assert "BTCUSDT" in text
    assert "2026-08-11T10:00:00+00:00" in text
    assert "canonical ProjectDatabase history" in text
