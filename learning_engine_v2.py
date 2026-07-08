"""Learning Engine 2.0 skeleton for SharipovAI.

Stores structured lessons in memory/demo form. Later this can be backed by a
file or database. The important part is the contract: every error should become
a lesson, and every lesson should become a rule candidate.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


DEFAULT_LESSONS: list[dict[str, Any]] = [
    {
        "id": "lesson-news-confirmation",
        "created_at": _now_iso(),
        "source": "News Supervisor",
        "error_type": "unconfirmed_news",
        "lesson": "Социальная новость не должна влиять на сделку без 2+ независимых подтверждений.",
        "new_rule": "Если source_kind=social и confirmations<2, Trade Gate обязан вернуть WAIT/BLOCK.",
        "status": "active_rule_candidate",
    },
    {
        "id": "lesson-live-lock",
        "created_at": _now_iso(),
        "source": "Security/Cyber AI",
        "error_type": "live_safety",
        "lesson": "LIVE торговля не должна включаться автоматически даже при хорошем demo-сигнале.",
        "new_rule": "can_trade_live всегда false без ручного unlock и отдельного security checklist.",
        "status": "active_rule_candidate",
    },
]


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def learning_state() -> dict[str, Any]:
    """Return current learning engine demo state."""

    return {
        "status": "ok",
        "engine": "Learning Engine 2.0",
        "mode": "demo_memory",
        "lesson_count": len(DEFAULT_LESSONS),
        "active_rule_candidates": [lesson for lesson in DEFAULT_LESSONS if lesson.get("status") == "active_rule_candidate"],
        "missing": [
            "Нужна постоянная база данных уроков.",
            "Нужна автоматическая привязка урока к конкретной сделке/новости/ошибке.",
            "Нужен approval workflow: правило сначала кандидат, потом утверждение.",
        ],
    }


def propose_lesson(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a structured lesson proposal from an error payload."""

    payload = payload or {}
    error_type = str(payload.get("error_type", "unknown_error"))
    source = str(payload.get("source", "SharipovAI"))
    description = str(payload.get("description", "Ошибка без описания"))
    return {
        "status": "ok",
        "proposal": {
            "id": f"lesson-{error_type.replace('_', '-')}",
            "created_at": _now_iso(),
            "source": source,
            "error_type": error_type,
            "lesson": description,
            "new_rule": _rule_from_error(error_type),
            "status": "needs_human_approval",
        },
    }


def _rule_from_error(error_type: str) -> str:
    rules = {
        "high_spread": "Если spread_percent > 0.25, Trade Gate возвращает WAIT.",
        "low_credibility_news": "Если news_credibility_percent < 65, Trade Gate возвращает BLOCK или WAIT.",
        "loss_streak": "После 2 подряд demo loss включить cooldown.",
        "api_unstable": "Если exchange_ok=false, сделки запрещены.",
    }
    return rules.get(error_type, "Добавить новое правило после ручного анализа ошибки.")
