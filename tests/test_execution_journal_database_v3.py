from __future__ import annotations

import json
from pathlib import Path

import pytest

from autonomous_trading.execution_journal import ExecutionJournal
from storage import ProjectDatabase, VersionConflict


def database(tmp_path: Path) -> ProjectDatabase:
    value = ProjectDatabase(f"sqlite:///{tmp_path / 'shared.db'}")
    value.initialize()
    return value


def test_legacy_json_migrates_once_without_duplicates(tmp_path: Path) -> None:
    path = tmp_path / "journal.json"
    path.write_text(json.dumps({"orders": [
        {"recorded_at": "2026-01-01T00:00:00+00:00", "status": "accepted", "mode": "sandbox"},
        {"recorded_at": "2026-01-01T00:00:01+00:00", "status": "blocked_or_error", "mode": "sandbox"},
    ]}), encoding="utf-8")
    db = database(tmp_path)
    first = ExecutionJournal(str(path), database=db)
    assert len(first.load()["orders"]) == 2
    second = ExecutionJournal(str(path), database=db)
    assert len(second.load()["orders"]) == 2
    assert db.get_json("migrations", "execution_journal_json_v1")["value"]["completed"] is True


def test_append_is_immutable_and_caller_cannot_spoof_recording_fields(tmp_path: Path) -> None:
    journal = ExecutionJournal(str(tmp_path / "journal.json"), database=database(tmp_path))
    item = journal.append({
        "journal_event_id": "event-1",
        "recorded_at": "spoofed",
        "recorded_at_ms": 1,
        "status": "accepted",
        "environment": "testnet",
    })
    assert item["journal_event_id"] == "event-1"
    assert item["recorded_at"] != "spoofed"
    assert item["recorded_at_ms"] > 1
    with pytest.raises(VersionConflict):
        journal.append({"journal_event_id": "event-1", "status": "accepted"})


def test_database_is_source_of_truth_when_backup_fails(tmp_path: Path, monkeypatch) -> None:
    journal = ExecutionJournal(str(tmp_path / "journal.json"), database=database(tmp_path))
    monkeypatch.setattr(journal, "_write_backup", lambda: (_ for _ in ()).throw(PermissionError("locked")))
    item = journal.append({"journal_event_id": "event-1", "status": "unresolved"})
    assert item["backup_status"] == "error"
    loaded = journal.load()["orders"]
    assert len(loaded) == 1 and loaded[0]["status"] == "unresolved"


def test_journal_does_not_truncate_and_multiple_instances_share_records(tmp_path: Path) -> None:
    db = database(tmp_path)
    first = ExecutionJournal(str(tmp_path / "journal-a.json"), database=db)
    second = ExecutionJournal(str(tmp_path / "journal-b.json"), database=db)
    for index in range(25):
        target = first if index % 2 == 0 else second
        target.append({
            "journal_event_id": f"event-{index:03d}",
            "status": "accepted" if index < 20 else "unresolved",
            "environment": "testnet",
        })
    assert len(first.load()["orders"]) == 25
    summary = second.summary()
    assert summary["recorded_orders"] == 25
    assert summary["accepted_orders"] == 20
    assert summary["unresolved_orders"] == 5
    assert summary["retention_truncated"] is False


def test_non_finite_evidence_is_rejected(tmp_path: Path) -> None:
    journal = ExecutionJournal(str(tmp_path / "journal.json"), database=database(tmp_path))
    with pytest.raises(ValueError):
        journal.append({"status": "accepted", "price": float("nan")})
