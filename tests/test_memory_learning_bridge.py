from __future__ import annotations

from memory_engine import DevelopmentLearningMemoryBridge, MemoryService, MemorySettings
from storage import ProjectDatabase


def test_learning_bridge_passively_copies_canonical_events(tmp_path):
    database = ProjectDatabase(dsn=f"sqlite:///{tmp_path / 'memory.db'}")
    database.initialize()
    database.append_event(
        "development_learning_events",
        "development_fix_outcome",
        "fix-1",
        {"success": True, "validation_sha256": "a" * 64},
        event_id="event-1",
        created_at_ms=1,
    )
    service = MemoryService(database, settings=MemorySettings(enabled=True))
    service.initialize()
    bridge = DevelopmentLearningMemoryBridge(service, database)

    first = bridge.collect_once()
    second = bridge.collect_once()

    assert first["seen"] == 1
    assert service.repository.stats()["raw_logs"] == 1
    assert second["seen"] == 1
    assert service.repository.stats()["raw_logs"] == 1
