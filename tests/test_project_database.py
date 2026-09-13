from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

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


def _wal_failure(monkeypatch, *, code, failures, statement="PRAGMA journal_mode=WAL"):
    original_connect = sqlite3.connect
    connections = []

    class InterruptedConnection(sqlite3.Connection):
        wal_calls = 0

        def execute(self, sql, *args, **kwargs):
            if sql == statement:
                self.wal_calls += 1
                if failures is None or self.wal_calls <= failures:
                    # Deliberately lock-like text must not make non-busy codes
                    # retryable; numeric SQLite results are authoritative.
                    error = sqlite3.OperationalError("database is locked")
                    if code is not None:
                        error.sqlite_errorcode = code
                    raise error
            return super().execute(sql, *args, **kwargs)

    def connect(*args, **kwargs):
        connection = original_connect(*args, factory=InterruptedConnection, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr("storage.project_database.sqlite3.connect", connect)
    return connections


@pytest.mark.parametrize("code", [
    sqlite3.SQLITE_BUSY, sqlite3.SQLITE_BUSY_RECOVERY,
    sqlite3.SQLITE_LOCKED, sqlite3.SQLITE_LOCKED_SHAREDCACHE,
])
def test_sqlite_wal_busy_recovers_without_changing_transaction_settings(tmp_path, monkeypatch, code):
    connections = _wal_failure(monkeypatch, code=code, failures=1)
    with ProjectDatabase(f"sqlite:///{tmp_path / 'retry.db'}").connect() as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 10_000
        connection.execute("CREATE TABLE preserved (id INTEGER)")
        connection.execute("INSERT INTO preserved VALUES (1)")
        assert connection.execute("SELECT id FROM preserved").fetchone()[0] == 1
    assert connections[0].wal_calls == 2
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connections[0].execute("SELECT 1")


@pytest.mark.parametrize("code", [sqlite3.SQLITE_BUSY_RECOVERY, sqlite3.SQLITE_LOCKED])
def test_sqlite_wal_permanent_busy_has_bounded_wait_and_closes_connection(tmp_path, monkeypatch, code):
    connections = _wal_failure(monkeypatch, code=code, failures=None)
    clock = [0.0]
    monkeypatch.setattr("storage.project_database.time.monotonic", lambda: clock[0])
    monkeypatch.setattr("storage.project_database.time.sleep", lambda delay: clock.__setitem__(0, clock[0] + delay))
    with pytest.raises(sqlite3.OperationalError) as error:
        with ProjectDatabase(f"sqlite:///{tmp_path / 'bounded.db'}").connect():
            pytest.fail("a permanently busy database must not be yielded")
    assert error.value.sqlite_errorcode == code
    assert 0 < clock[0] <= 10.0
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connections[0].execute("SELECT 1")


@pytest.mark.parametrize("code", [sqlite3.SQLITE_READONLY, sqlite3.SQLITE_IOERR, sqlite3.SQLITE_ERROR, None])
def test_sqlite_wal_nonbusy_failure_is_immediate_and_closes_connection(tmp_path, monkeypatch, code):
    connections = _wal_failure(monkeypatch, code=code, failures=None)
    monkeypatch.setattr("storage.project_database.time.sleep", lambda _: pytest.fail("must not retry non-busy errors"))
    with pytest.raises(sqlite3.OperationalError) as error:
        with ProjectDatabase(f"sqlite:///{tmp_path / 'readonly.db'}").connect():
            pytest.fail("setup failure must propagate")
    assert getattr(error.value, "sqlite_errorcode", None) == code
    assert connections[0].wal_calls == 1
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connections[0].execute("SELECT 1")


@pytest.mark.parametrize("statement", ["PRAGMA foreign_keys=ON", "PRAGMA busy_timeout=10000"])
def test_sqlite_later_setup_failure_closes_connection(tmp_path, monkeypatch, statement):
    connections = _wal_failure(monkeypatch, code=sqlite3.SQLITE_ERROR, failures=None, statement=statement)
    with pytest.raises(sqlite3.OperationalError):
        with ProjectDatabase(f"sqlite:///{tmp_path / 'setup.db'}").connect():
            pytest.fail("incomplete setup must not be yielded")
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connections[0].execute("SELECT 1")


def test_sqlite_wal_promotion_waits_for_real_writer_and_preserves_committed_data(tmp_path, monkeypatch):
    path = tmp_path / "writer.db"
    writer = sqlite3.connect(path, isolation_level=None)
    writer.execute("CREATE TABLE preserved (id INTEGER)")
    writer.execute("BEGIN IMMEDIATE")
    writer.execute("INSERT INTO preserved VALUES (7)")
    contention_seen = Event()
    original_connect = sqlite3.connect

    class ObservedConnection(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            try:
                return super().execute(sql, *args, **kwargs)
            except sqlite3.OperationalError as error:
                if sql == "PRAGMA journal_mode=WAL" and (error.sqlite_errorcode & 0xFF) == sqlite3.SQLITE_BUSY:
                    contention_seen.set()
                raise

    monkeypatch.setattr("storage.project_database.sqlite3.connect",
                        lambda *args, **kwargs: original_connect(*args, factory=ObservedConnection, **kwargs))

    def initialize():
        database = ProjectDatabase(f"sqlite:///{path}")
        database.initialize()
        with database.connect() as connection:
            return (connection.execute("SELECT id FROM preserved").fetchone()[0],
                    connection.execute("PRAGMA journal_mode").fetchone()[0])

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(initialize)
            try:
                assert contention_seen.wait(timeout=5), "test must force real WAL contention"
            finally:
                writer.execute("COMMIT")
            assert pending.result(timeout=5) == (7, "wal")
    finally:
        writer.close()


def test_sqlite_caller_transaction_failure_is_not_replayed(tmp_path, monkeypatch):
    calls = 0
    error = sqlite3.OperationalError("caller transaction busy")
    error.sqlite_errorcode = sqlite3.SQLITE_BUSY
    monkeypatch.setattr("storage.project_database.time.sleep", lambda _: pytest.fail("must not replay caller"))
    with pytest.raises(sqlite3.OperationalError) as raised:
        with ProjectDatabase(f"sqlite:///{tmp_path / 'caller.db'}").connect() as connection:
            calls += 1
            raise error
    assert raised.value is error
    assert calls == 1
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")
