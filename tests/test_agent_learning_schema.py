from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from storage import ProjectDatabase


def _database(tmp_path: Path) -> ProjectDatabase:
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'agent-learning.db'}")
    database.initialize()
    return database


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}


def test_agent_learning_tables_are_created_idempotently(tmp_path: Path) -> None:
    database = _database(tmp_path)
    database.initialize()
    with database.connect() as connection:
        tables = {
            str(row[0])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert {"agent_fixes", "agent_decisions", "agent_decision_events"} <= tables
        assert {
            "fix_id", "error_signature", "patch", "patch_sha256", "success", "source",
            "base_sha", "applied_sha", "validation_json", "metadata_json",
            "attempt_count", "created_at_ms", "updated_at_ms",
        } <= _table_columns(connection, "agent_fixes")
        assert {
            "decision_id", "fix_id", "kind", "status", "base_sha", "patch_sha256",
            "security_verdict", "security_details_json", "proposal_json",
            "protected_paths_json", "actor", "risk_level", "requires_approval",
            "created_at_ms", "updated_at_ms", "decided_at_ms",
        } <= _table_columns(connection, "agent_decisions")
        assert {
            "event_id", "decision_id", "event_type", "actor", "payload_json", "created_at_ms",
        } <= _table_columns(connection, "agent_decision_events")
    assert database.health()["schema_version"] == 2


def test_agent_learning_schema_upgrades_existing_version_one_database(tmp_path: Path) -> None:
    path = tmp_path / "upgrade.db"
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, applied_at_ms BIGINT NOT NULL)"
    )
    connection.execute("INSERT INTO schema_migrations(version, applied_at_ms) VALUES (1, 1)")
    connection.commit()
    connection.close()

    database = ProjectDatabase(f"sqlite:///{path}")
    database.initialize()
    with database.connect() as upgraded:
        versions = [
            int(row[0])
            for row in upgraded.execute("SELECT version FROM schema_migrations ORDER BY version")
        ]
        tables = {
            str(row[0])
            for row in upgraded.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert versions == [1, 2]
    assert {"agent_fixes", "agent_decisions", "agent_decision_events"} <= tables


def test_agent_decision_foreign_keys_and_constraints(tmp_path: Path) -> None:
    database = _database(tmp_path)
    patch_sha = "a" * 64
    base_sha = "b" * 40
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO agent_fixes(
                fix_id, error_signature, patch, patch_sha256, success, source,
                base_sha, applied_sha, validation_json, metadata_json,
                attempt_count, created_at_ms, updated_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "fix-1", "ValueError: deterministic signature", "diff --git a/a.py b/a.py\n",
                patch_sha, 0, "self_healing_agent", base_sha, "", "{}", "{}", 1, 10, 10,
            ),
        )
        connection.execute(
            """
            INSERT INTO agent_decisions(
                decision_id, fix_id, kind, status, base_sha, patch_sha256,
                security_verdict, security_details_json, proposal_json,
                protected_paths_json, actor, risk_level, requires_approval,
                created_at_ms, updated_at_ms, decided_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "decision-1", "fix-1", "security_review", "approved", base_sha, patch_sha,
                "allow", "{}", "{}", "[]", "security_guard", "low", 1, 11, 12, 12,
            ),
        )
        connection.execute(
            "INSERT INTO agent_decision_events(event_id, decision_id, event_type, actor, payload_json, created_at_ms) VALUES (?, ?, ?, ?, ?, ?)",
            ("event-1", "decision-1", "approved", "security_guard", "{}", 12),
        )
        connection.commit()
        connection.execute("DELETE FROM agent_fixes WHERE fix_id = ?", ("fix-1",))
        decision = connection.execute(
            "SELECT fix_id FROM agent_decisions WHERE decision_id = ?", ("decision-1",)
        ).fetchone()
        assert decision is not None and decision[0] is None
        connection.execute("DELETE FROM agent_decisions WHERE decision_id = ?", ("decision-1",))
        assert connection.execute(
            "SELECT COUNT(*) FROM agent_decision_events WHERE decision_id = ?", ("decision-1",)
        ).fetchone()[0] == 0
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO agent_fixes(
                    fix_id, error_signature, patch, patch_sha256, success, source,
                    base_sha, applied_sha, validation_json, metadata_json,
                    attempt_count, created_at_ms, updated_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "fix-invalid", "signature", "diff --git a/a b/a\n", patch_sha, 2,
                    "test", base_sha, "", "{}", "{}", 0, 1, 1,
                ),
            )
