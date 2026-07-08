"""Persistent learning memory for SharipovAI Learning OS.

Stores lessons, rules, mistakes and exam results in SQLite. This is the durable
memory layer that turns self-learning from static packs into accumulated,
queryable knowledge.
"""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from typing import Any


DEFAULT_DB = "data/learning_memory.sqlite3"


def default_db_path() -> Path:
    return Path(os.getenv("LEARNING_MEMORY_DB", DEFAULT_DB))


class LearningMemory:
    """SQLite-backed learning memory."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def record_mistake(self, *, bot: str, domain: str, mistake: str, consequence: str, source: str = "system") -> dict[str, Any]:
        now = int(time.time())
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO mistakes(bot, domain, mistake, consequence, source, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (_bot(bot), domain, mistake, consequence, source, now),
            )
            mistake_id = int(cur.lastrowid)
        lesson = self.create_lesson_from_mistake(mistake_id)
        return {"status": "ok", "mistake_id": mistake_id, "lesson": lesson}

    def create_lesson_from_mistake(self, mistake_id: int) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM mistakes WHERE id = ?", (mistake_id,)).fetchone()
            if row is None:
                return {"status": "not_found", "mistake_id": mistake_id}
            lesson_text = f"Если обнаружена ошибка: {row['mistake']}, бот должен снизить уверенность, проверить источник и объяснить риск."
            rule_text = f"Для домена {row['domain']} запрещено действовать без проверки причины, риска и источника."
            now = int(time.time())
            cur = conn.execute(
                "INSERT INTO lessons(bot, domain, lesson, rule, source, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (row["bot"], row["domain"], lesson_text, rule_text, f"mistake:{mistake_id}", now),
            )
            lesson_id = int(cur.lastrowid)
        return {"status": "ok", "lesson_id": lesson_id, "lesson": lesson_text, "rule": rule_text}

    def add_lesson(self, *, bot: str, domain: str, lesson: str, rule: str, source: str = "manual") -> dict[str, Any]:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO lessons(bot, domain, lesson, rule, source, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (_bot(bot), domain, lesson, rule, source, int(time.time())),
            )
            return {"status": "ok", "lesson_id": int(cur.lastrowid)}

    def record_exam(self, *, bot: str, score: float, passed: bool, details: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO exams(bot, score, passed, details, created_at) VALUES (?, ?, ?, ?, ?)",
                (_bot(bot), float(score), 1 if passed else 0, str(details or {}), int(time.time())),
            )
            return {"status": "ok", "exam_id": int(cur.lastrowid)}

    def lessons_for_bot(self, bot: str, *, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM lessons WHERE bot = ? OR bot = 'all' ORDER BY created_at DESC, id DESC LIMIT ?",
                (_bot(bot), int(limit)),
            ).fetchall()
        return [_row(row) for row in rows]

    def snapshot(self) -> dict[str, Any]:
        with self._connect() as conn:
            lesson_count = int(conn.execute("SELECT COUNT(*) FROM lessons").fetchone()[0])
            mistake_count = int(conn.execute("SELECT COUNT(*) FROM mistakes").fetchone()[0])
            exam_count = int(conn.execute("SELECT COUNT(*) FROM exams").fetchone()[0])
            recent_lessons = [_row(row) for row in conn.execute("SELECT * FROM lessons ORDER BY created_at DESC, id DESC LIMIT 20").fetchall()]
            recent_exams = [_row(row) for row in conn.execute("SELECT * FROM exams ORDER BY created_at DESC, id DESC LIMIT 20").fetchall()]
        return {
            "status": "ok",
            "lesson_count": lesson_count,
            "mistake_count": mistake_count,
            "exam_count": exam_count,
            "recent_lessons": recent_lessons,
            "recent_exams": recent_exams,
        }

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS mistakes(id INTEGER PRIMARY KEY AUTOINCREMENT, bot TEXT NOT NULL, domain TEXT NOT NULL, mistake TEXT NOT NULL, consequence TEXT NOT NULL, source TEXT NOT NULL, created_at INTEGER NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS lessons(id INTEGER PRIMARY KEY AUTOINCREMENT, bot TEXT NOT NULL, domain TEXT NOT NULL, lesson TEXT NOT NULL, rule TEXT NOT NULL, source TEXT NOT NULL, created_at INTEGER NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS exams(id INTEGER PRIMARY KEY AUTOINCREMENT, bot TEXT NOT NULL, score REAL NOT NULL, passed INTEGER NOT NULL, details TEXT NOT NULL, created_at INTEGER NOT NULL)"
            )


def _bot(bot: str) -> str:
    return bot.strip().lower().replace("-", "_").replace(" ", "_")


def _row(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}
