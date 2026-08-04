from __future__ import annotations

import json
from pathlib import Path

from storage.project_database import ProjectDatabase


def _database(tmp_path: Path) -> ProjectDatabase:
    return ProjectDatabase(f"sqlite:///{tmp_path / 'agent-learning.db'}")


def test_agent_learning_tables_and_indexes_are_created(tmp_path: Path) -> None:
    database = _database(tmp_path)
    database.initialize()
    database.initialize()  # migration must be idempotent

    assert database.health()["schema_version"] == 2
    with database.connect() as connection:
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        indexes = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            ).fetchall()
        }

    assert {"agent_fixes", "agent_decisions", "agent_decision_events"} <= tables
    assert {
        "agent_fixes_signature_idx",
        "agent_decisions_status_idx",
        "agent_decisions_fix_idx",
        "agent_decision_events_lookup_idx",
    } <= indexes


def test_agent_learning_foreign_keys_and_event_cascade(tmp_path: Path) -> None:
    database = _database(tmp_path)
    database.initialize()

    with database.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            INSERT INTO agent_fixes(
                fix_id, error_signature, patch, success, source,
                failure_reason, metadata_json, created_at_ms, updated_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "fix-1",
                "sqlite3.DatabaseError:file is not a database",
                "diff --git a/a.py b/a.py\n",
                1,
                "self_healing_agent",
                "",
                json.dumps({"tests": ["test_database"]}),
                1000,
                1000,
            ),
        )
        connection.execute(
            """
            INSERT INTO agent_decisions(
                decision_id, fix_id, kind, status, base_sha, patch_sha256,
                security_verdict, proposal_json, created_at_ms, updated_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "decision-1",
                "fix-1",
                "apply",
                "applied",
                "abcdef1",
                "a" * 64,
                "allowed",
                json.dumps({"proposal_id": "proposal-1"}),
                1000,
                1100,
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
                "applied",
                "self-healing-agent",
                json.dumps({"result": "ok"}),
                1100,
            ),
        )
        connection.commit()

        connection.execute("DELETE FROM agent_decisions WHERE decision_id = ?", ("decision-1",))
        assert connection.execute(
            "SELECT COUNT(*) FROM agent_decision_events WHERE decision_id = ?",
            ("decision-1",),
        ).fetchone()[0] == 0

        connection.execute(
            """
            INSERT INTO agent_decisions(
                decision_id, fix_id, kind, status, base_sha, patch_sha256,
                security_verdict, proposal_json, created_at_ms, updated_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "decision-2",
                "fix-1",
                "learn",
                "learned",
                "abcdef1",
                "b" * 64,
                "allowed",
                "{}",
                1200,
                1200,
            ),
        )
        connection.execute("DELETE FROM agent_fixes WHERE fix_id = ?", ("fix-1",))
        row = connection.execute(
            "SELECT fix_id FROM agent_decisions WHERE decision_id = ?",
            ("decision-2",),
        ).fetchone()
        assert row["fix_id"] is None
