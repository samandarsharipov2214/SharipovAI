from __future__ import annotations

from fastapi.testclient import TestClient

from learning.ai_learning_core import BOT_NAMES
from learning.bot_communication import BotCommunicationNetwork
from learning.bot_communication_app import app


def test_communication_matrix_is_full_mesh(tmp_path) -> None:
    network = BotCommunicationNetwork(tmp_path / "bot_network.sqlite3")

    matrix = network.communication_matrix()

    assert matrix["status"] == "ok"
    assert matrix["full_mesh_possible"] is True
    assert matrix["missing_links"] == []
    assert len(matrix["bots"]) == len(BOT_NAMES)
    for sender in BOT_NAMES:
        for recipient in BOT_NAMES:
            assert matrix["matrix"][sender][recipient] is (sender != recipient)


def test_send_message_inbox_outbox_thread_and_read(tmp_path) -> None:
    network = BotCommunicationNetwork(tmp_path / "bot_network.sqlite3")

    result = network.send_message(
        sender="general_controller",
        recipient="risk_engine",
        message_type="question",
        topic="risk",
        payload={"question": "Can we trade?"},
        priority="high",
    )

    assert result["status"] == "ok"
    inbox = network.inbox("risk_engine", unread_only=True)
    outbox = network.outbox("general_controller")
    thread = network.thread(result["thread_id"])

    assert len(inbox) == 1
    assert inbox[0]["payload"]["question"] == "Can we trade?"
    assert len(outbox) == 1
    assert len(thread["messages"]) == 1

    read = network.mark_read(result["message_id"])
    assert read["status"] == "ok"
    assert network.inbox("risk_engine", unread_only=True) == []


def test_reply_keeps_same_thread(tmp_path) -> None:
    network = BotCommunicationNetwork(tmp_path / "bot_network.sqlite3")
    sent = network.send_message(
        sender="general_controller",
        recipient="news_agent",
        message_type="question",
        topic="news",
        payload={"question": "Any urgent news?"},
    )

    reply = network.reply(original_message_id=sent["message_id"], sender="news_agent", payload={"answer": "No urgent confirmed news."})
    thread = network.thread(sent["thread_id"])

    assert reply["status"] == "ok"
    assert reply["thread_id"] == sent["thread_id"]
    assert len(thread["messages"]) == 2
    assert thread["messages"][1]["recipient"] == "general_controller"


def test_broadcast_reaches_all_other_bots(tmp_path) -> None:
    network = BotCommunicationNetwork(tmp_path / "bot_network.sqlite3")

    result = network.broadcast(
        sender="general_controller",
        message_type="status_update",
        topic="system",
        payload={"status": "check communication"},
    )

    assert result["status"] == "ok"
    assert result["sent"] == len(BOT_NAMES) - 1
    assert network.health()["message_count"] == len(BOT_NAMES) - 1


def test_consensus_request_targets_key_bots(tmp_path) -> None:
    network = BotCommunicationNetwork(tmp_path / "bot_network.sqlite3")

    result = network.request_consensus(topic="trade", question="Should we allow paper trade?")
    thread = network.thread(result["thread_id"])

    assert result["status"] == "ok"
    assert result["sent"] == 5
    recipients = {message["recipient"] for message in thread["messages"]}
    assert {"market_agent", "news_agent", "risk_engine", "portfolio_engine", "confidence_engine"}.issubset(recipients)


def test_bot_communication_api(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOT_COMMUNICATION_DB", str(tmp_path / "bot_network.sqlite3"))
    client = TestClient(app)

    health = client.get("/api/bot-network/health")
    assert health.status_code == 200
    assert health.json()["full_mesh_possible"] is True

    sent = client.post(
        "/api/bot-network/messages",
        json={"sender": "general_controller", "recipient": "risk_engine", "message_type": "question", "topic": "risk", "payload": {"q": "risk?"}},
    )
    assert sent.status_code == 200
    assert sent.json()["status"] == "ok"

    inbox = client.get("/api/bot-network/inbox/risk_engine?unread_only=true")
    assert inbox.status_code == 200
    assert len(inbox.json()["messages"]) == 1

    page = client.get("/bot-network")
    assert page.status_code == 200
    assert "Связь AI-ботов" in page.text
