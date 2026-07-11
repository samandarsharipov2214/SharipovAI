from __future__ import annotations

from pathlib import Path

import pytest

from storage import DatabaseUnavailable, ProjectDatabase, VersionConflict


def _db(tmp_path: Path) -> ProjectDatabase:
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'shared.db'}")
    database.initialize()
    return database


def test_health_and_shared_kv(tmp_path: Path) -> None:
    database = _db(tmp_path)
    assert database.health()["status"] == "ok"
    assert database.put_json("project", "settings", {"safe": True}) == 1
    assert database.put_json("project", "settings", {"safe": False}, expected_version=1) == 2
    stored = database.get_json("project", "settings")
    assert stored and stored["value"] == {"safe": False} and stored["version"] == 2
    with pytest.raises(VersionConflict):
        database.put_json("project", "settings", {}, expected_version=1)


def test_events_messages_and_ai_state_are_shared(tmp_path: Path) -> None:
    database = _db(tmp_path)
    event_id = database.append_event("evidence", "decision", "candidate-1", {"decision": "BLOCK"}, created_at_ms=1)
    assert database.list_events("evidence")[0]["event_id"] == event_id
    database.append_message(project_id="SharipovAI", chat_id="chat-a", message_id="m-1", role="user", content="remember this", created_at_ms=2)
    database.append_message(project_id="SharipovAI", chat_id="chat-b", message_id="m-2", role="assistant", content="shared response", created_at_ms=3)
    assert [item["message_id"] for item in database.list_messages(project_id="SharipovAI")] == ["m-1", "m-2"]
    assert database.set_ai_state("security_guard", {"kill_switch": True}) == 1
    state = database.get_ai_state("security_guard")
    assert state and state["state"]["kill_switch"] is True


def test_duplicate_message_is_idempotent(tmp_path: Path) -> None:
    database = _db(tmp_path)
    kwargs = dict(project_id="SharipovAI", chat_id="chat", message_id="same", role="user", content="one")
    database.append_message(**kwargs)
    database.append_message(**kwargs)
    assert len(database.list_messages(project_id="SharipovAI")) == 1


def test_non_finite_json_is_rejected(tmp_path: Path) -> None:
    database = _db(tmp_path)
    with pytest.raises(ValueError):
        database.put_json("market", "bad", {"price": float("nan")})


def test_required_database_fails_without_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("SHARIPOVAI_DATABASE_REQUIRED", "1")
    with pytest.raises(DatabaseUnavailable):
        ProjectDatabase()


def test_default_local_database_is_single_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("SHARIPOVAI_DATABASE_REQUIRED", "0")
    monkeypatch.setenv("SHARIPOVAI_DATA_DIR", str(tmp_path))
    database = ProjectDatabase()
    database.initialize()
    assert (tmp_path / "sharipovai_shared.db").exists()
