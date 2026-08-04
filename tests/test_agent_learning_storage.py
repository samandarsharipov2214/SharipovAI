from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from storage import ProjectDatabase


def _database(tmp_path: Path) -> ProjectDatabase:
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'agent-learning.db'}")
    database.initialize()
    return database


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row["name"]) for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}


def test_agent_learning_migration_creates_version_two_schema(tmp_path: Path) -> None:
    database = _database(tmp_path)
    assert database.health()["schema_version"] == 2

    with database.connect() as connection:
        assert {
            "fix_id",
            "error_signature",
            "patch",
            "patch_sha256",
            "base_sha",
            "result_sha",
            "success",
            "source",
            "context_json",
            "validation_json",
            "failure_reason",
            "created_at_ms",
            "updated_at_ms",
        } <= _columns(connection, "agent_fixes")
        assert {
            "decision_id",
            "fix_id",
            "kind",
            "status",
            "base_sha",
            "patch_sha256",
            "security_verdict",
            "security_reasons_json",
            "proposal_json",
            "actor",
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


def test_agent_fix_decision_and_event_chain_is_persistent(tmp_path: Path) -> None:
    database = _database(tmp_path)
    patch_sha = "a" * 64
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO agent_fixes(
                fix_id, error_signature, patch, patch_sha256, base_sha, result_sha,
                success, source, context_json, validation_json, failure_reason,
                created_at_ms, updated_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "fix-1",
                "DatabaseError:file-is-not-a-database",
                "diff --git a/a.py b/a.py\n",
                patch_sha,
                "1a2b3c4",
                "",
                None,
                "self-healing-agent",
                json.dumps({"container": "sharipovai"}),
                json.dumps({"tests": []}),
                "",
                1,
                1,
            ),
        )
        connection.execute(
            """
            INSERT INTO agent_decisions(
                decision_id, fix_id, kind, status, base_sha, patch_sha256,
                security_verdict, security_reasons_json, proposal_json, actor,
                created_at_ms, updated_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "decision-1",
                "fix-1",
                "security_review",
                "approved",
                "1a2b3c4",
                patch_sha,
                "allowed",
                "[]",
                json.dumps({"proposal_id": "proposal-1"}),
                "security_guard",
                2,
                2,
            ),
        )
        connection.execute(
            """
            INSERT INTO agent_decision_events(
                event_id, decision_id, event_type, actor, payload_json, created_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "event-1",
                "decision-1",
                "security_review_completed",
                "security_guard",
                json.dumps({"allowed": True}),
                3,
            ),
        )
        connection.commit()

    database.initialize()
    with database.connect() as connection:
        fix = connection.execute("SELECT * FROM agent_fixes WHERE fix_id = ?", ("fix-1",)).fetchone()
        decision = connection.execute(
            "SELECT * FROM agent_decisions WHERE decision_id = ?", ("decision-1",)
        ).fetchone()
        event = connection.execute(
            "SELECT * FROM agent_decision_events WHERE event_id = ?", ("event-1",)
        ).fetchone()
    assert fix and fix["error_signature"] == "DatabaseError:file-is-not-a-database"
    assert decision and decision["security_verdict"] == "allowed"
    assert event and json.loads(event["payload_json"]) == {"allowed": True}


def test_agent_learning_foreign_keys_are_fail_closed(tmp_path: Path) -> None:
    database = _database(tmp_path)
    with database.connect() as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO agent_decisions(
                decision_id, fix_id, kind, status, base_sha, patch_sha256,
                security_verdict, security_reasons_json, proposal_json, actor,
                created_at_ms, updated_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "orphan-decision",
                "missing-fix",
                "proposal",
                "pending",
                "1a2b3c4",
                "b" * 64,
                "not_checked",
                "[]",
                "{}",
                "general_controller",
                1,
                1,
            ),
        )


def test_agent_learning_indexes_exist(tmp_path: Path) -> None:
    database = _database(tmp_path)
    with database.connect() as connection:
        indexes = {
            str(row["name"])
            for table in ("agent_fixes", "agent_decisions", "agent_decision_events")
            for row in connection.execute(f"PRAGMA index_list({table})").fetchall()
        }
    assert {
        "agent_fixes_signature_idx",
        "agent_fixes_success_idx",
        "agent_decisions_fix_idx",
        "agent_decisions_status_idx",
        "agent_decision_events_lookup_idx",
    } <= indexes
