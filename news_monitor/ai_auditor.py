"""Auditor for the autonomous specialized News AI network."""

from __future__ import annotations

from typing import Any

from .agent_bridge import bridge_status
from .agent_network import network_status

CREDENTIAL_AGENTS = {
    "telegram_news_ai": "Нужен Telegram client/bot доступ к allowlist каналам.",
    "x_news_ai": "Нужен X API/Bearer Token или другой легальный X data provider.",
    "youtube_news_ai": "Нужен YouTube API/RSS reader и отделение мнения от факта.",
}

CRITICAL_AGENTS = {"politics_ai", "world_ai", "economy_ai", "finance_ai", "crypto_ai", "security_ai"}


def audit_news_ai() -> dict[str, object]:
    """Audit every specialized News AI with memory, freshness and routing proof."""

    network = network_status(run_due=True)
    agents = list(network.get("agents", []))
    interviews = [_interview(agent) for agent in agents]
    working = [item for item in interviews if item["verdict"] == "работает"]
    underbuilt = [item for item in interviews if item["verdict"] in {"частично работает", "нет свежих данных", "ошибка"}]
    fake_like = [item for item in interviews if item["verdict"] == "заглушка"]
    bridge = bridge_status()
    grade = _grade(len(working), len(interviews), len(fake_like), len(underbuilt), bool(bridge.get("thread_alive")))
    return {
        "status": "ok",
        "source_mode": "specialized_agent_network",
        "auditor": {
            "name": "Specialized News AI Auditor",
            "role": "Проверяет независимые циклы, память, freshness, источники, ошибки и маршрутизацию каждого News AI.",
            "overall_grade": grade,
            "working": len(working),
            "underbuilt": len(underbuilt),
            "fake_like": len(fake_like),
            "total": len(interviews),
            "bridge_alive": bool(bridge.get("thread_alive")),
            "summary": _summary(grade, len(working), len(interviews), len(underbuilt), bridge),
        },
        "interviews": interviews,
        "priority_actions": _priority_actions(interviews, bridge),
        "supervisor": network.get("coordinator", {}),
        "bridge": bridge,
    }


def _interview(agent: dict[str, Any]) -> dict[str, object]:
    agent_id = str(agent.get("id", "unknown"))
    status = str(agent.get("status", "unknown"))
    source_count = int(agent.get("source_count", 0) or 0)
    item_count = int(agent.get("item_count", 0) or 0)
    health = int(agent.get("health_score", 0) or 0)
    freshness = agent.get("data_freshness_seconds")
    memory_count = int(agent.get("memory_count", 0) or 0)
    events = int(agent.get("events_emitted", 0) or 0)
    verdict = _verdict(agent_id, status, source_count, item_count, health, freshness)
    problems = _problems(agent_id, status, source_count, item_count, health, freshness)
    return {
        "id": agent_id,
        "name": str(agent.get("name", "Unknown News AI")),
        "scope": "news",
        "critical": agent_id in CRITICAL_AGENTS,
        "status": status,
        "health_score": health,
        "source_count": source_count,
        "item_count": item_count,
        "memory_count": memory_count,
        "events_emitted": events,
        "data_freshness_seconds": freshness,
        "average_credibility_percent": float(agent.get("average_credibility_percent", 0) or 0),
        "verdict": verdict,
        "problems": problems,
        "missing": problems,
        "next_fix": _next_fix(agent_id, verdict),
        "last_seen": agent.get("last_seen"),
        "last_action": agent.get("last_action"),
        "routes_to": agent.get("routes_to", []),
        "interview": [
            {"q": "Какая твоя зона?", "a": str(agent.get("mission", "Не указана"))},
            {"q": "Сколько реальных источников назначено?", "a": str(source_count)},
            {"q": "Сколько свежих материалов обработано?", "a": str(item_count)},
            {"q": "Есть ли собственная память?", "a": f"да, записей: {memory_count}"},
            {"q": "Куда ты передаёшь события?", "a": ", ".join(agent.get("routes_to", [])) or "маршруты не настроены"},
            {"q": "Твой честный статус?", "a": verdict},
        ],
    }


def _verdict(agent_id: str, status: str, source_count: int, item_count: int, health: int, freshness: object) -> str:
    if source_count <= 0:
        return "заглушка"
    if status == "waiting_credentials":
        return "частично работает"
    if status == "error":
        return "ошибка"
    if status == "stale" or item_count <= 0:
        return "нет свежих данных"
    if health < 60:
        return "частично работает"
    try:
        if freshness is None or int(freshness) > 900:
            return "нет свежих данных"
    except (TypeError, ValueError):
        return "нет свежих данных"
    return "работает"


def _problems(agent_id: str, status: str, source_count: int, item_count: int, health: int, freshness: object) -> list[str]:
    problems: list[str] = []
    if source_count <= 0:
        problems.append("Нет назначенных источников.")
    if item_count <= 0:
        problems.append("Нет свежих обработанных материалов.")
    if agent_id in CREDENTIAL_AGENTS and status == "waiting_credentials":
        problems.append(CREDENTIAL_AGENTS[agent_id])
    if status == "error":
        problems.append("Есть ошибки чтения принадлежащих агенту источников.")
    if health < 70:
        problems.append("Health ниже 70%.")
    try:
        if freshness is None or int(freshness) > 900:
            problems.append("Данные устарели более чем на 15 минут.")
    except (TypeError, ValueError):
        problems.append("Freshness неизвестен.")
    return problems or ["Критических проблем не найдено."]


def _next_fix(agent_id: str, verdict: str) -> str:
    if agent_id in CREDENTIAL_AGENTS:
        return CREDENTIAL_AGENTS[agent_id]
    if verdict == "заглушка":
        return "Назначить реальные RSS/API/official источники или отключить агента."
    if verdict == "нет свежих данных":
        return "Проверить RSS autorun, source errors и data_freshness_seconds."
    if verdict == "ошибка":
        return "Открыть /api/social-news/rss/refresh и исправить ошибки принадлежащих источников."
    if verdict == "частично работает":
        return "Повысить health: увеличить реальное покрытие, память и подтверждение источников."
    return "Продолжать независимые циклы и проверку качества событий."


def _priority_actions(interviews: list[dict[str, object]], bridge: dict[str, Any]) -> list[str]:
    actions = [str(item.get("next_fix")) for item in interviews if item.get("verdict") != "работает"]
    if not bridge.get("thread_alive"):
        actions.insert(0, "Запустить News Agent Bridge: события не доходят до Risk/Trading/Portfolio/Learning.")
    actions.append("Проверять /api/news-agents/status и память каждого агента после Render deploy.")
    return list(dict.fromkeys(action for action in actions if action))


def _grade(working: int, total: int, fake_like: int, underbuilt: int, bridge_alive: bool) -> str:
    if total <= 0 or fake_like:
        return "WEAK"
    if not bridge_alive:
        return "PARTIAL"
    ratio = working / total
    if ratio >= 0.75 and underbuilt <= 3:
        return "GOOD"
    if ratio >= 0.4:
        return "PARTIAL"
    return "WEAK"


def _summary(grade: str, working: int, total: int, underbuilt: int, bridge: dict[str, Any]) -> str:
    return (
        f"Specialized News AI: полноценно работают {working}/{total}; требуют внимания {underbuilt}. "
        f"Bridge к системным ботам: {'работает' if bridge.get('thread_alive') else 'не работает'}. "
        f"Итоговая оценка: {grade}."
    )
