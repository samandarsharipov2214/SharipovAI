from __future__ import annotations

from memory_engine import MemoryService, MemorySettings
from storage import ProjectDatabase


def test_disabled_memory_is_a_true_noop(tmp_path):
    service = MemoryService(
        ProjectDatabase(dsn=f"sqlite:///{tmp_path / 'disabled.db'}"),
        settings=MemorySettings(enabled=False),
    )

    assert service.initialize()["status"] == "disabled"
    assert service.record_dialog(
        team_id="sharipovai",
        user_id="owner",
        agent_id="learning_engine",
        session_id="s1",
        message="hello",
        source_ref="test:1",
    ) is None
    assert not (tmp_path / "disabled.db").exists()


def test_passive_collection_redacts_secret_like_values(tmp_path):
    service = MemoryService(
        ProjectDatabase(dsn=f"sqlite:///{tmp_path / 'enabled.db'}"),
        settings=MemorySettings(enabled=True),
    )
    assert service.initialize()["status"] == "ok"

    log = service.record_dialog(
        team_id="sharipovai",
        user_id="owner",
        agent_id="learning_engine",
        session_id="s1",
        message="token=super-secret-value regression fixed",
        source_ref="test:1",
    )

    assert log is not None
    assert "super-secret-value" not in log.content
    assert "REDACTED_SECRET" in log.content
    assert service.get_context(
        agent_id="learning_engine",
        user_id="owner",
        query_text="regression",
    ) == []


def test_extraction_stays_disabled_independently(tmp_path):
    service = MemoryService(
        ProjectDatabase(dsn=f"sqlite:///{tmp_path / 'enabled.db'}"),
        settings=MemorySettings(enabled=True, extraction_enabled=False),
    )
    service.initialize()
    assert service.extract_pending() == {"status": "disabled", "processed": 0, "facts": 0}
