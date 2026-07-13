from __future__ import annotations

import json

from paper_activity_engine import PaperActivityEngine


def test_virtual_account_state_write_is_atomic_and_revisioned(tmp_path) -> None:
    path = tmp_path / "virtual-account.json"
    engine = PaperActivityEngine(path=path)

    engine._save({"cash": 9_900.0, "equity": 9_900.0, "trades": []})
    first = json.loads(path.read_text(encoding="utf-8"))
    next_state = engine._load()
    next_state["cash"] = 9_800.0
    next_state["equity"] = 9_800.0
    engine._save(next_state)
    second = json.loads(path.read_text(encoding="utf-8"))

    assert first["state_revision"] == 1
    assert second["state_revision"] == 2
    assert engine.backup_path.exists()
    assert not list(tmp_path.glob("*.tmp"))
    assert second["real_orders_blocked"] is True
    assert second["live_execution_enabled"] is False


def test_corrupt_primary_recovers_last_known_good_backup(tmp_path) -> None:
    path = tmp_path / "virtual-account.json"
    engine = PaperActivityEngine(path=path)

    engine._save({"cash": 9_900.0, "equity": 9_900.0, "trades": []})
    next_state = engine._load()
    next_state["cash"] = 9_800.0
    next_state["equity"] = 9_800.0
    engine._save(next_state)
    path.write_text("{broken json", encoding="utf-8")

    recovered = engine._load()

    assert recovered["cash"] == 9_900.0
    assert recovered["state_recovered_from_backup"] is True
    assert recovered["state_recovery_source"].endswith(".json.bak")
    assert recovered["real_orders_blocked"] is True
