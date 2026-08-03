from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from storage import ProjectDatabase


def _database(tmp_path: Path) -> ProjectDatabase:
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'agent-learning.db'}")
    database.initialize()
    return database


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row["name"]) for row in connection.execute(f"PRAGMA table_info({table})")}


def test_agent_learning_migration_creates_versioned_tables_and_indexes(tmp_path: Path) -> None:
    database = _database(tmp_path)

    with database.connect() as connection:
        versions = [int(row["version"]) for row in connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        )]
        tables = {
            str(row["name"])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        indexes = {
            str(row["name"])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            )
        }

        assert versions == [1, 2]
        assert {"agent_fixes", "agent_decisions", "agent_decision_events"} <= tables
        assert {
            "agent_fixes_signature_idx",
            "agent_fixes_patch_idx",
            "agent_decisions_fix_idx",
            "agent_decisions_status_idx",
            "agent_decision_events_lookup_idx",
        } <= indexes

        assert {
            "fix_id",
            "error_signature",
            "failure_class",
            "patch",
            "patch_sha256",
            "success",
            "source",
            "base_sha",
            "applied_sha",
            "attempt_count",
            "test_evidence_json",
            "metadata_json",
            "created_at_ms",
            "updated_at_ms",
        } <= _columns(connection, "agent_fixes")
        assert {
            "decision_id",
            "fix_id",
            "kind",
            "status",
            "base_sha",
            "target_branch",
            "patch_sha256",
            "security_verdict",
            "actor",
            "rationale",
            "metadata_json",
            "created_at_ms",
            "updated_at_ms",
        } <= _columns(connection, "agent_decisions")
        assert {
            "event_id",
            "decision_id",
            "event_type",
            "actor",
            "payload_json",
            "created_at_ms",
        } <= _columns(connection, "agent_decision_events")


def test_migration_upgrades_existing_version_one_database_and_is_idempotent(tmp_path: Path) -> None:
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'legacy.db'}")
    with database.connect() as connection:
        connection.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at_ms BIGINT NOT NULL)"
        )
        connection.execute("INSERT INTO schema_migrations(version, applied_at_ms) VALUES (1, 1)")
        connection.commit()

    database.initialize()
    database.initialize()

    with database.connect() as connection:
        assert connection.execute(
            "SELECT MAX(version) FROM schema_migrations"
        ).fetchone()[0] == 2
        assert connection.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version = 2"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'agent_fixes'"
        ).fetchone()[0] == 1


def test_repair_memory_and_decision_ledger_round_trip_with_foreign_keys(tmp_path: Path) -> None:
    database = _database(tmp_path)
    base_sha = "a" * 40
    patch = "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-old\n+new\n"
    patch_sha256 = hashlib.sha256(patch.encode("utf-8")).hexdigest()

    fix_id = database.record_agent_fix(
        fix_id="fix-1",
        error_signature="RuntimeError: database is locked",
        failure_class="database_lock",
        patch=patch,
        success=True,
        source="self_healing_agent",
        base_sha=base_sha,
        applied_sha="b" * 40,
        attempt_count=2,
        test_evidence={"pytest": "passed"},
        metadata={"incident": "inc-1"},
        created_at_ms=10,
    )
    decision_id = database.record_agent_decision(
        decision_id="decision-1",
        fix_id=fix_id,
        kind="approve",
        status="approved",
        base_sha=base_sha,
        target_branch="main",
        patch_sha256=patch_sha256,
        security_verdict="allow",
        actor="security_guard",
        rationale="Patch is bounded and tests passed.",
        metadata={"policy": "development-v1"},
        created_at_ms=20,
    )
    event_id = database.append_agent_decision_event(
        event_id="event-1",
        decision_id=decision_id,
        event_type="approved",
        actor="general_controller",
        payload={"checks": ["pytest", "protected_path_guard"]},
        created_at_ms=30,
    )

    fix = database.get_agent_fix(fix_id)
    decision = database.get_agent_decision(decision_id)
    events = database.list_agent_decision_events(decision_id)

    assert fix is not None
    assert fix["patch_sha256"] == patch_sha256
    assert fix["success"] is True
    assert fix["test_evidence"] == {"pytest": "passed"}
    assert decision is not None
    assert decision["fix_id"] == fix_id
    assert decision["security_verdict"] == "allow"
    assert events == [
        {
            "event_id": event_id,
            "decision_id": decision_id,
            "event_type": "approved",
            "actor": "general_controller",
            "payload": {"checks": ["pytest", "protected_path_guard"]},
            "created_at_ms": 30,
        }
    ]

    with database.connect() as connection:
        connection.execute("DELETE FROM agent_decisions WHERE decision_id = ?", (decision_id,))
        connection.commit()
        assert connection.execute(
            "SELECT COUNT(*) FROM agent_decision_events WHERE decision_id = ?",
            (decision_id,),
        ).fetchone()[0] == 0


def test_decision_event_requires_existing_decision(tmp_path: Path) -> None:
    database = _database(tmp_path)

    with pytest.raises(sqlite3.IntegrityError):
        database.append_agent_decision_event(
            decision_id="missing",
            event_type="approved",
            actor="security_guard",
            payload={},
            created_at_ms=1,
        )


def test_agent_fix_rejects_invalid_sha_and_non_finite_evidence(tmp_path: Path) -> None:
    database = _database(tmp_path)

    with pytest.raises(ValueError):
        database.record_agent_fix(
            error_signature="error",
            patch="patch",
            success=False,
            source="test",
            base_sha="not-a-sha",
        )

    with pytest.raises(ValueError):
        database.record_agent_fix(
            error_signature="error",
            patch="patch",
            success=False,
            source="test",
            test_evidence={"score": float("nan")},
        )
