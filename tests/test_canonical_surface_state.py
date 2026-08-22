from __future__ import annotations

from canonical_surface_state import _scope_for_path, load_canonical_paper_state
from storage import ProjectDatabase


def _database(tmp_path) -> ProjectDatabase:
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'project.db'}")
    database.initialize()
    return database


def test_canonical_surface_state_fails_closed_when_runtime_state_is_missing(tmp_path, monkeypatch) -> None:
    database = _database(tmp_path)
    monkeypatch.setenv("AUTONOMOUS_PAPER_STATE_FILE", str(tmp_path / "paper.json"))

    state = load_canonical_paper_state(database)

    assert state["status"] == "unavailable"
    assert state["mode"] == "PAPER"
    assert state["source_of_truth"] == "ProjectDatabase/CouncilAuthorizedPaperLoop"
    assert state["real_orders_blocked"] is True
    assert state["equity"] == 0.0


def test_canonical_surface_uses_the_same_durable_default_path_as_runtime(tmp_path, monkeypatch) -> None:
    database = _database(tmp_path)
    monkeypatch.delenv("AUTONOMOUS_PAPER_STATE_FILE", raising=False)
    data_dir = tmp_path / "durable-data"
    monkeypatch.setenv("SHARIPOVAI_DATA_DIR", str(data_dir))
    scope = _scope_for_path(data_dir / "autonomous_paper.json")
    database.put_json("autonomous_paper_state", scope, {"equity": 10_000.0, "positions": {}})

    state = load_canonical_paper_state(database)

    assert state["status"] == "ok"
    assert state["equity"] == 10_000.0


def test_canonical_surface_state_reads_database_backed_account_and_bounded_trade_window(tmp_path, monkeypatch) -> None:
    database = _database(tmp_path)
    state_path = tmp_path / "paper.json"
    monkeypatch.setenv("AUTONOMOUS_PAPER_STATE_FILE", str(state_path))
    scope = _scope_for_path(state_path)

    database.put_json(
        "autonomous_paper_state",
        scope,
        {
            "equity": 10125.0,
            "cash": 9000.0,
            "realized_pnl": 75.0,
            "unrealized_pnl": 50.0,
            "total_fees": 12.5,
            "positions": {"BTCUSDT": {"quantity": 0.01}},
        },
    )
    for index in range(3):
        database.put_json(
            f"paper_trades:{scope}",
            f"trade-{index}",
            {"trade_id": f"trade-{index}", "realized_pnl": float(index)},
        )

    state = load_canonical_paper_state(database)

    assert state["status"] == "ok"
    assert state["database_backed"] is True
    assert state["equity"] == 10125.0
    assert state["net_pnl"] == 125.0
    assert state["open_positions"] == 1
    assert state["trade_history_count"] == 3
    assert state["trade_history_window_count"] == 3
    assert state["trade_history_complete"] is True
    assert state["real_orders_blocked"] is True
