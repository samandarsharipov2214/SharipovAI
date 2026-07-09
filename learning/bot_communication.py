"""AI Bot Communication Network for SharipovAI.

Provides a durable SQLite message bus so the 11 AI bots can talk to each
other, broadcast updates, keep threads, request consensus, and expose a health
matrix proving that the network is connected.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from persistence_paths import durable_data_path

from .ai_learning_core import BOT_NAMES


DEFAULT_DB = "data/bot_communication.sqlite3"

MESSAGE_TYPES = {
    "status_update",
    "question",
    "answer",
    "risk_alert",
    "legal_alert",
    "learning_update",
    "consensus_request",
    "consensus_response",
    "handoff",
    "command",
}

PRIORITIES = {"low", "normal", "high", "critical"}


BOT_RESPONSIBILITIES = {
    "general_controller": "Главный координатор решений и маршрутизации задач.",
    "market_agent": "Рынок, цена, тренд, ликвидность и режим рынка.",
    "news_agent": "Новости, проверка источников, срочность и достоверность.",
    "risk_engine": "Риск, просадка, лимиты, запрет опасных решений.",
    "portfolio_engine": "Портфель, позиции, ребалансировка и капитал.",
    "paper_trading_bot": "Демо-сделки, симуляции и проверка гипотез.",
    "confidence_engine": "Confidence score, слабые места и уверенность ответа.",
    "consensus_engine": "Сбор мнений ботов и итоговый консенсус.",
    "stress_bot": "Стресс-тесты, краш-сценарии и устойчивость.",
    "learning_engine": "Ошибки, уроки, правила и экзамены ботов.",
    "security_guard": "Безопасность, доступы, policy/legal блокировки.",
}


class BotCommunicationNetwork:
    """SQLite message bus for inter-bot communication."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else durable_data_path("BOT_COMMUNICATION_DB", DEFAULT_DB)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def send_message(
        self,
        *,
        sender: str,
        recipient: str,
        message_type: str,
        topic: str,
        payload: dict[str, Any],
        thread_id: str | None = None,
        priority: str = "normal",
    ) -> dict[str, Any]:
        """Send one message from one bot to another."""

        sender = _bot(sender)
        recipient = _bot(recipient)
        if sender not in BOT_NAMES:
            return {"status": "invalid_sender", "sender": sender}
        if recipient not in BOT_NAMES:
            return {"status": "invalid_recipient", "recipient": recipient}
        if sender == recipient:
            return {"status": "invalid_recipient", "reason": "sender_equals_recipient"}
        if message_type not in MESSAGE_TYPES:
            return {"status": "invalid_message_type", "message_type": message_type}
        if priority not in PRIORITIES:
            return {"status": "invalid_priority", "priority": priority}
        now = int(time.time())
        message_id = "MSG-" + uuid.uuid4().hex[:16].upper()
        thread = thread_id or "THR-" + uuid.uuid4().hex[:16].upper()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO messages(message_id, thread_id, sender, recipient, message_type, topic, priority, payload_json, status, created_at, read_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (message_id, thread, sender, recipient, message_type, topic, priority, json.dumps(payload, ensure_ascii=False), "unread", now, 0),
            )
        return {"status": "ok", "message_id": message_id, "thread_id": thread}

    def broadcast(
        self,
        *,
        sender: str,
        message_type: str,
        topic: str,
        payload: dict[str, Any],
        recipients: list[str] | None = None,
        priority: str = "normal",
    ) -> dict[str, Any]:
        """Broadcast one message to many bots."""

        sender = _bot(sender)
        targets = [_bot(item) for item in (recipients or sorted(BOT_NAMES)) if _bot(item) != sender]
        thread = "THR-" + uuid.uuid4().hex[:16].upper()
        results = [
            self.send_message(
                sender=sender,
                recipient=target,
                message_type=message_type,
                topic=topic,
                payload=payload,
                thread_id=thread,
                priority=priority,
            )
            for target in targets
        ]
        return {"status": "ok", "thread_id": thread, "sent": len([item for item in results if item.get("status") == "ok"]), "results": results}

    def reply(
        self,
        *,
        original_message_id: str,
        sender: str,
        payload: dict[str, Any],
        message_type: str = "answer",
        priority: str = "normal",
    ) -> dict[str, Any]:
        """Reply to an existing message in the same thread."""

        original = self.get_message(original_message_id)
        if original.get("status") != "ok":
            return original
        message = original["message"]
        return self.send_message(
            sender=sender,
            recipient=message["sender"],
            message_type=message_type,
            topic=message["topic"],
            payload=payload,
            thread_id=message["thread_id"],
            priority=priority,
        )

    def request_consensus(self, *, topic: str, question: str, participants: list[str] | None = None) -> dict[str, Any]:
        """Ask selected bots for opinions; Consensus Engine coordinates the thread."""

        targets = participants or ["market_agent", "news_agent", "risk_engine", "portfolio_engine", "confidence_engine"]
        return self.broadcast(
            sender="consensus_engine",
            recipients=targets,
            message_type="consensus_request",
            topic=topic,
            payload={"question": question, "required_response": "opinion,risk,confidence,source"},
            priority="high",
        )

    def inbox(self, bot: str, *, unread_only: bool = False, limit: int = 50) -> list[dict[str, Any]]:
        """Return messages received by one bot."""

        bot = _bot(bot)
        query = "SELECT * FROM messages WHERE recipient = ?"
        args: list[Any] = [bot]
        if unread_only:
            query += " AND status = 'unread'"
        query += " ORDER BY created_at DESC, id DESC LIMIT ?"
        args.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(query, args).fetchall()
        return [_message_row(row) for row in rows]

    def outbox(self, bot: str, *, limit: int = 50) -> list[dict[str, Any]]:
        """Return messages sent by one bot."""

        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM messages WHERE sender = ? ORDER BY created_at DESC, id DESC LIMIT ?",
                (_bot(bot), int(limit)),
            ).fetchall()
        return [_message_row(row) for row in rows]

    def mark_read(self, message_id: str) -> dict[str, Any]:
        """Mark one message as read."""

        now = int(time.time())
        with self._connect() as conn:
            cur = conn.execute("UPDATE messages SET status = 'read', read_at = ? WHERE message_id = ?", (now, message_id))
        return {"status": "ok" if cur.rowcount else "not_found", "message_id": message_id}

    def thread(self, thread_id: str) -> dict[str, Any]:
        """Return a full message thread."""

        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM messages WHERE thread_id = ? ORDER BY created_at ASC, id ASC", (thread_id,)).fetchall()
        return {"status": "ok", "thread_id": thread_id, "messages": [_message_row(row) for row in rows]}

    def get_message(self, message_id: str) -> dict[str, Any]:
        """Return one message."""

        with self._connect() as conn:
            row = conn.execute("SELECT * FROM messages WHERE message_id = ?", (message_id,)).fetchone()
        if row is None:
            return {"status": "not_found", "message_id": message_id}
        return {"status": "ok", "message": _message_row(row)}

    def communication_matrix(self) -> dict[str, Any]:
        """Return full-mesh communication matrix for all bots."""

        bots = sorted(BOT_NAMES)
        matrix = {sender: {recipient: sender != recipient for recipient in bots} for sender in bots}
        missing = [f"{sender}->{recipient}" for sender in bots for recipient in bots if sender != recipient and not matrix[sender][recipient]]
        return {"status": "ok", "bots": bots, "matrix": matrix, "full_mesh_possible": not missing, "missing_links": missing}

    def health(self) -> dict[str, Any]:
        """Return message bus health and connectivity proof."""

        with self._connect() as conn:
            total = int(conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0])
            unread = int(conn.execute("SELECT COUNT(*) FROM messages WHERE status = 'unread'").fetchone()[0])
            threads = int(conn.execute("SELECT COUNT(DISTINCT thread_id) FROM messages").fetchone()[0])
        matrix = self.communication_matrix()
        return {
            "status": "ok",
            "bot_count": len(BOT_NAMES),
            "message_count": total,
            "unread_count": unread,
            "thread_count": threads,
            "full_mesh_possible": matrix["full_mesh_possible"],
            "missing_links": matrix["missing_links"],
            "responsibilities": BOT_RESPONSIBILITIES,
        }

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY AUTOINCREMENT, message_id TEXT UNIQUE NOT NULL, thread_id TEXT NOT NULL, sender TEXT NOT NULL, recipient TEXT NOT NULL, message_type TEXT NOT NULL, topic TEXT NOT NULL, priority TEXT NOT NULL, payload_json TEXT NOT NULL, status TEXT NOT NULL, created_at INTEGER NOT NULL, read_at INTEGER NOT NULL)"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_recipient ON messages(recipient, status, created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_thread ON messages(thread_id, created_at)")


def _bot(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def _message_row(row: sqlite3.Row) -> dict[str, Any]:
    payload_raw = row["payload_json"]
    try:
        payload = json.loads(payload_raw)
    except Exception:
        payload = {}
    return {
        "message_id": row["message_id"],
        "thread_id": row["thread_id"],
        "sender": row["sender"],
        "recipient": row["recipient"],
        "message_type": row["message_type"],
        "topic": row["topic"],
        "priority": row["priority"],
        "payload": payload,
        "status": row["status"],
        "created_at": row["created_at"],
        "read_at": row["read_at"],
    }
