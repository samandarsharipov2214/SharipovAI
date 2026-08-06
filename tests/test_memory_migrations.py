from __future__ import annotations

import pytest

from memory_engine import MemoryMigrationManager
from storage import ProjectDatabase


def _db(tmp_path):
    return ProjectDatabase(dsn=f"sqlite:///{tmp_path / 'memory.db'}")


def test_memory_schema_is_versioned_and_isolated(tmp_path):
    manager = MemoryMigrationManager(_db(tmp_path))
    health = manager.initialize()

    assert health["status"] == "ok"
    assert health["schema_version"] == 1
    assert set(health["counts"]) == {
        "memory_raw_logs",
        "memory_facts",
        "memory_scenarios",
        "memory_core",
    }


def test_memory_rollback_requires_explicit_confirmation(tmp_path):
    manager = MemoryMigrationManager(_db(tmp_path))
    manager.initialize()

    with pytest.raises(RuntimeError, match="confirmed"):
        manager.rollback()

    manager.rollback(confirmed=True)
    assert manager.health()["status"] == "error"
