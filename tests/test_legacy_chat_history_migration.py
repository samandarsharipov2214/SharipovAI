from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from dashboard.legacy_chat_history_migration import (
    LegacyChatMigrationError,
    backfill_legacy_web_chat_history,
)
from dashboard.models_saas import Base, ChatMessageLog, User
from storage.project_database import ProjectDatabase


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_backfill_preserves_history_metadata_timestamps_and_is_idempotent(tmp_path):
    db = _session()
    user = User(
        id="user-legacy-1",
        email="legacy@example.com",
        password_hash="test-hash",
        display_name="Legacy User",
    )
    started = datetime(2026, 8, 20, 1, 2, 3, tzinfo=UTC)
    db.add(user)
    db.add_all(
        [
            ChatMessageLog(
                id="legacy-message-user",
                user=user,
                role="user",
                content="old question",
                model_name="gemini-test",
                request_id="legacy-request",
                source="gemini",
                created_at=started,
            ),
            ChatMessageLog(
                id="legacy-message-assistant",
                user=user,
                role="assistant",
                content="old answer",
                model_name="gemini-test",
                request_id="legacy-request",
                source="gemini",
                created_at=started + timedelta(seconds=1),
            ),
        ]
    )
    db.commit()

    canonical = ProjectDatabase(f"sqlite:///{tmp_path / 'shared.db'}")
    first = backfill_legacy_web_chat_history(db, database=canonical, batch_size=1)
    second = backfill_legacy_web_chat_history(db, database=canonical, batch_size=1)

    assert first == {"legacy_rows_attempted": 2, "users_seen": 1}
    assert second == first

    history = canonical.list_messages(
        project_id="sharipovai",
        chat_id="web-user-legacy-1",
    )
    assert len(history) == 2
    assert [item["message_id"] for item in history] == [
        "legacy-web-legacy-message-user",
        "legacy-web-legacy-message-assistant",
    ]
    assert [item["role"] for item in history] == ["user", "assistant"]
    assert [item["content"] for item in history] == ["old question", "old answer"]
    assert history[0]["created_at_ms"] == int(started.timestamp() * 1000)
    assert history[1]["created_at_ms"] == int((started + timedelta(seconds=1)).timestamp() * 1000)

    user_metadata = history[0]["metadata"]
    assert user_metadata["actor_id"] == "user-legacy-1"
    assert user_metadata["actor_email"] == "legacy@example.com"
    assert user_metadata["actor_type"] == "user"
    assert user_metadata["channel"] == "web"
    assert user_metadata["legacy_source_table"] == "saas_chat_messages"
    assert user_metadata["legacy_message_id"] == "legacy-message-user"
    assert user_metadata["request_id"] == "legacy-request"

    assistant_metadata = history[1]["metadata"]
    assert assistant_metadata["actor_id"] == "system-gemini"
    assert assistant_metadata["actor_type"] == "system"
    assert assistant_metadata["legacy_message_id"] == "legacy-message-assistant"


def test_backfill_fails_closed_on_unrepresentable_legacy_role(tmp_path):
    db = _session()
    user = User(
        id="user-legacy-2",
        email="bad-role@example.com",
        password_hash="test-hash",
    )
    db.add(user)
    db.add(
        ChatMessageLog(
            id="legacy-message-tool",
            user=user,
            role="tool",
            content="unexpected legacy role",
            source="gemini",
            created_at=datetime(2026, 8, 20, tzinfo=UTC),
        )
    )
    db.commit()

    canonical = ProjectDatabase(f"sqlite:///{tmp_path / 'shared.db'}")
    with pytest.raises(LegacyChatMigrationError, match="unsupported legacy chat role"):
        backfill_legacy_web_chat_history(db, database=canonical)

    assert canonical.list_messages(
        project_id="sharipovai",
        chat_id="web-user-legacy-2",
    ) == []
