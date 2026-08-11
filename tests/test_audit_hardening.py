from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from scripts.db_restore_drill import validate_sqlite_backup
from scripts.execution_path_guard import scan_file, scan_repository
from scripts.project_db_retention import run_retention
from storage.project_database import ProjectDatabase


def test_execution_path_guard_blocks_noncanonical_order_call(tmp_path: Path) -> None:
    module = tmp_path / "rogue.py"
    module.write_text("def run(client):\n    return client.place_order(symbol='BTCUSDT')\n", encoding="utf-8")
    violations = scan_file(module, root=tmp_path)
    assert [(item.path, item.call) for item in violations] == [("rogue.py", "place_order")]


def test_execution_path_guard_allows_canonical_execution_file(tmp_path: Path) -> None:
    path = tmp_path / "exchange_connector" / "bybit_execution.py"
    path.parent.mkdir(parents=True)
    path.write_text("def run(client):\n    return client.place_order(symbol='BTCUSDT')\n", encoding="utf-8")
    assert scan_file(path, root=tmp_path) == []


def test_repository_has_no_second_direct_execution_path() -> None:
    assert scan_repository(Path(__file__).resolve().parents[1]) == []


def test_retention_is_dry_run_by_default_and_protects_evidence(tmp_path: Path) -> None:
    db = ProjectDatabase(f"sqlite:///{tmp_path / 'retention.db'}")
    db.initialize()
    old = int(time.time() * 1000) - 40 * 86_400_000
    db.append_event("market_cache", "tick", "btc", {"price": 1}, created_at_ms=old)
    db.append_event("evidence", "proof", "keep", {"hash": "x"}, created_at_ms=old)
    result = run_retention(db=db, retain_days=30, batch_size=100, apply=False)
    assert result.eligible_rows == 1
    assert result.deleted_rows == 0
    assert len(db.list_events("market_cache")) == 1
    assert len(db.list_events("evidence")) == 1


def test_retention_apply_deletes_only_unprotected_old_events(tmp_path: Path) -> None:
    db = ProjectDatabase(f"sqlite:///{tmp_path / 'retention.db'}")
    db.initialize()
    old = int(time.time() * 1000) - 40 * 86_400_000
    recent = int(time.time() * 1000)
    db.append_event("market_cache", "tick", "old", {"price": 1}, created_at_ms=old)
    db.append_event("market_cache", "tick", "new", {"price": 2}, created_at_ms=recent)
    db.append_event("execution", "order", "protected", {"status": "x"}, created_at_ms=old)
    result = run_retention(db=db, retain_days=30, batch_size=100, apply=True)
    assert result.deleted_rows == 1
    assert [item["entity_id"] for item in db.list_events("market_cache")] == ["new"]
    assert len(db.list_events("execution")) == 1


def test_retention_never_deletes_canonical_decision_risk_portfolio_or_learning_history(tmp_path: Path) -> None:
    db = ProjectDatabase(f"sqlite:///{tmp_path / 'retention.db'}")
    db.initialize()
    old = int(time.time() * 1000) - 40 * 86_400_000
    protected = (
        "decision_quality",
        "trading_candidates",
        "risk_assessments",
        "portfolio_snapshots",
        "council_market_evidence",
        "paper_decision_settlements",
        "self_learning_events",
    )
    for namespace in protected:
        db.append_event(namespace, "proof", namespace, {"keep": True}, created_at_ms=old)
    db.append_event("news_fetch_observations", "source_fetch", "old-news", {"keep": False}, created_at_ms=old)

    result = run_retention(db=db, retain_days=30, batch_size=100, apply=True)

    assert result.deleted_rows == 1
    assert db.list_events("news_fetch_observations") == []
    for namespace in protected:
        assert len(db.list_events(namespace)) == 1, namespace


def test_retention_rejects_dangerously_short_window(tmp_path: Path) -> None:
    db = ProjectDatabase(f"sqlite:///{tmp_path / 'retention.db'}")
    with pytest.raises(ValueError, match="at least 7"):
        run_retention(db=db, retain_days=1, batch_size=100, apply=False)


def test_restore_drill_validates_copy_without_mutating_source(tmp_path: Path) -> None:
    source = tmp_path / "backup.db"
    db = ProjectDatabase(f"sqlite:///{source}")
    db.initialize()
    db.append_event("audit", "probe", "one", {"ok": True})
    before = source.read_bytes()
    result = validate_sqlite_backup(source)
    after = source.read_bytes()
    assert result["status"] == "ok"
    assert result["integrity_check"] == "ok"
    assert before == after


def test_restore_drill_rejects_corrupt_backup(tmp_path: Path) -> None:
    source = tmp_path / "broken.db"
    source.write_bytes(b"not-a-sqlite-database")
    with pytest.raises(sqlite3.DatabaseError):
        validate_sqlite_backup(source)
