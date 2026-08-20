from storage.conversation_read_model import ConversationReadModel
from storage.project_database import ProjectDatabase
from storage.web_chat_persistence import persist_web_chat_completion


def test_web_chat_completion_uses_canonical_message_history(tmp_path):
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'shared.db'}")

    persist_web_chat_completion(
        user_id="user-123",
        user_email="user@example.com",
        user_message="hello",
        assistant_message="hi there",
        model_name="gemini-test",
        request_id="req-123",
        database=database,
    )

    history = ConversationReadModel(database).get_history(
        project_id="sharipovai",
        chat_id="web-user-123",
    )

    assert [item["role"] for item in history] == ["user", "assistant"]
    assert [item["content"] for item in history] == ["hello", "hi there"]
    assert history[0]["metadata"]["actor_id"] == "user-123"
    assert history[0]["metadata"]["actor_email"] == "user@example.com"
    assert history[0]["metadata"]["actor_type"] == "user"
    assert history[0]["metadata"]["channel"] == "web"
    assert history[1]["metadata"]["actor_id"] == "system-gemini"
    assert history[1]["metadata"]["actor_type"] == "system"
    assert history[1]["metadata"]["request_id"] == "req-123"


def test_web_chat_completion_retry_is_idempotent(tmp_path):
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'shared.db'}")
    payload = {
        "user_id": "user-456",
        "user_email": "retry@example.com",
        "user_message": "question",
        "assistant_message": "answer",
        "model_name": "gemini-test",
        "request_id": "req-retry",
        "database": database,
    }

    persist_web_chat_completion(**payload)
    persist_web_chat_completion(**payload)

    history = database.list_messages(
        project_id="sharipovai",
        chat_id="web-user-456",
    )
    assert len(history) == 2
    assert {item["message_id"] for item in history} == {
        "web-req-retry-user",
        "web-req-retry-assistant",
    }
