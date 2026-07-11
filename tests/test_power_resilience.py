from __future__ import annotations

import json

from autonomous_trading.power_resilience import PowerResilienceManager


def test_checkpoint_creates_last_known_good_backup(tmp_path) -> None:
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"value": 42}), encoding="utf-8")
    manager = PowerResilienceManager(files=[state_file])
    manager.root = tmp_path
    manager.manifest_path = tmp_path / "manifest.json"

    result = manager.checkpoint()

    assert result["status"] == "ok"
    backup = state_file.with_suffix(".json.lastgood")
    assert backup.exists()
    assert json.loads(backup.read_text(encoding="utf-8"))["value"] == 42
    assert json.loads(manager.manifest_path.read_text(encoding="utf-8"))["interval_seconds"] == 10.0


def test_recovery_restores_corrupted_primary(tmp_path) -> None:
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"balance": 100}), encoding="utf-8")
    manager = PowerResilienceManager(files=[state_file])
    manager.root = tmp_path
    manager.manifest_path = tmp_path / "manifest.json"
    manager.checkpoint()

    state_file.write_text('{"balance":', encoding="utf-8")
    result = manager.recover_all()

    assert result["status"] == "ok"
    assert str(state_file) in result["recovered"]
    assert json.loads(state_file.read_text(encoding="utf-8"))["balance"] == 100


def test_invalid_primary_and_backup_are_reported(tmp_path) -> None:
    state_file = tmp_path / "state.json"
    backup = state_file.with_suffix(".json.lastgood")
    state_file.write_text("broken", encoding="utf-8")
    backup.write_text("also broken", encoding="utf-8")
    manager = PowerResilienceManager(files=[state_file])
    manager.root = tmp_path
    manager.manifest_path = tmp_path / "manifest.json"

    result = manager.recover_all()

    assert result["status"] == "warning"
    assert result["failed"][0]["path"] == str(state_file)
