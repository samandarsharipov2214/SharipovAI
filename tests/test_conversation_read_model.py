from __future__ import annotations

from typing import Any

from storage.conversation_read_model import ConversationReadModel
from storage.project_database import ProjectDatabase


def _database(tmp_path) -> ProjectDatabase:
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'shared.db'}")
    database.initialize()
    return database


def _append(
    database: ProjectDatabase,
    *,
    chat_id: str,
    message_id: str,
    role: str,
    content: str,
    created_at_ms: int,
    metadata: dict[str, Any] | None = None,
) -> None:
    database.append_message(
        project_id="sharipovai",
        chat_id=chat_id,
        message_id=message_id,
        role=role,
        content=content,
        metadata=metadata or {"source": "test"},
        created_at_ms=created_at_ms,
    )


def test_conversation_index_is_derived_from_existing_canonical_messages(tmp_path) -> None:
    database = _database(tmp_path)
    _append(database, chat_id="web-1", message_id="m1", role="user", content="hello", created_at_ms=100)
    _append(database, chat_id="telegram-1", message_id="m2", role="user", content="ping", created_at_ms=200)
    _append(database, chat_id="web-1", message_id="m3", role="assistant", content="world", created_at_ms=300)

    index = ConversationReadModel(database).list_conversations(project_id="sharipovai")

    assert index.scan_truncated is False
    assert index.scanned_message_count == 3
    assert [item.chat_id for item in index.conversations] == ["web-1", "telegram-1"]
    web = index.conversations[0]
    assert web.message_count == 2
    assert web.first_message_at_ms == 100
    assert web.last_message_at_ms == 300
    assert web.last_role == "assistant"
    assert web.last_content == "world"
    assert web.channels == ()
    assert web.actor_ids == ()
    assert web.actor_types == ()


def test_conversation_index_exposes_stored_cross_channel_actor_provenance(tmp_path) -> None:
    database = _database(tmp_path)
    _append(
        database,
        chat_id="shared-user-1",
        message_id="m1",
        role="user",
        content="web question",
        created_at_ms=100,
        metadata={"channel": "web", "actor_id": "user-1", "actor_type": "user"},
    )
    _append(
        database,
        chat_id="shared-user-1",
        message_id="m2",
        role="assistant",
        content="web answer",
        created_at_ms=200,
        metadata={"channel": "web", "actor_id": "system-gemini", "actor_type": "system"},
    )
    _append(
        database,
        chat_id="shared-user-1",
        message_id="m3",
        role="user",
        content="telegram follow-up",
        created_at_ms=300,
        metadata={"channel": "telegram", "actor_id": "user-1", "actor_type": "user"},
    )
    _append(
        database,
        chat_id="shared-user-1",
        message_id="m4",
        role="assistant",
        content="mini app answer",
        created_at_ms=400,
        metadata={"channel": "miniapp", "actor_id": "system-gemini", "actor_type": "system"},
    )

    index = ConversationReadModel(database).list_conversations(project_id="sharipovai")

    assert len(index.conversations) == 1
    conversation = index.conversations[0]
    assert conversation.channels == ("miniapp", "telegram", "web")
    assert conversation.actor_ids == ("system-gemini", "user-1")
    assert conversation.actor_types == ("system", "user")


def test_missing_provenance_is_not_guessed_from_chat_id(tmp_path) -> None:
    database = _database(tmp_path)
    _append(
        database,
        chat_id="telegram-424242",
        message_id="m1",
        role="user",
        content="no metadata provenance",
        created_at_ms=100,
        metadata={"source": "legacy"},
    )

    conversation = ConversationReadModel(database).list_conversations(project_id="sharipovai").conversations[0]

    assert conversation.channels == ()
    assert conversation.actor_ids == ()
    assert conversation.actor_types == ()


def test_history_delegates_to_project_database_and_preserves_order(tmp_path) -> None:
    database = _database(tmp_path)
    _append(database, chat_id="shared-1", message_id="m2", role="assistant", content="second", created_at_ms=200)
    _append(database, chat_id="shared-1", message_id="m1", role="user", content="first", created_at_ms=100)

    history = ConversationReadModel(database).get_history(
        project_id="sharipovai",
        chat_id="shared-1",
    )

    assert [message["message_id"] for message in history] == ["m1", "m2"]
    assert [message["content"] for message in history] == ["first", "second"]


def test_duplicate_message_id_does_not_inflate_conversation_count(tmp_path) -> None:
    database = _database(tmp_path)
    _append(database, chat_id="web-1", message_id="same", role="user", content="original", created_at_ms=100)
    _append(database, chat_id="web-1", message_id="same", role="assistant", content="duplicate", created_at_ms=200)

    index = ConversationReadModel(database).list_conversations(project_id="sharipovai")
    history = ConversationReadModel(database).get_history(project_id="sharipovai", chat_id="web-1")

    assert index.conversations[0].message_count == 1
    assert len(history) == 1
    assert history[0]["content"] == "original"


def test_read_model_survives_database_reopen_without_migration_or_copy(tmp_path) -> None:
    database_path = tmp_path / "shared.db"
    database = ProjectDatabase(f"sqlite:///{database_path}")
    database.initialize()
    _append(database, chat_id="mini-app-1", message_id="m1", role="user", content="persisted", created_at_ms=100)

    reopened = ProjectDatabase(f"sqlite:///{database_path}")
    reopened.initialize()
    index = ConversationReadModel(reopened).list_conversations(project_id="sharipovai")

    assert len(index.conversations) == 1
    assert index.conversations[0].chat_id == "mini-app-1"
    assert index.conversations[0].last_content == "persisted"


def test_scan_limit_is_fail_closed_when_projection_may_be_partial(tmp_path) -> None:
    database = _database(tmp_path)
    _append(database, chat_id="chat-1", message_id="m1", role="user", content="one", created_at_ms=100)
    _append(database, chat_id="chat-2", message_id="m2", role="user", content="two", created_at_ms=200)

    index = ConversationReadModel(database).list_conversations(
        project_id="sharipovai",
        message_scan_limit=1,
    )

    assert index.scan_truncated is True
    assert index.scanned_message_count == 1
    assert len(index.conversations) == 1
    assert index.conversations[0].chat_id == "chat-2"


def test_bounded_conversation_scan_prefers_newest_messages(tmp_path) -> None:
    database = _database(tmp_path)
    _append(database, chat_id="old", message_id="m1", role="user", content="old", created_at_ms=100)
    _append(database, chat_id="middle", message_id="m2", role="user", content="middle", created_at_ms=200)
    _append(database, chat_id="new", message_id="m3", role="user", content="new", created_at_ms=300)

    index = ConversationReadModel(database).list_conversations(
        project_id="sharipovai",
        message_scan_limit=2,
    )

    assert index.scan_truncated is True
    assert index.scanned_message_count == 2
    assert [item.chat_id for item in index.conversations] == ["new", "middle"]
