"""AI auditor for checking subsystem News AI operability.

The auditor runs a scripted interview with every News AI agent and marks whether
it is active, partially implemented, credential-blocked, or placeholder-like.
"""

from __future__ import annotations

from typing import Any

from .agents import run_news_agents


REAL_DATA_REQUIRED = {
    "telegram_news_ai": "Нужен Telegram client/bot доступ к каналам или группам.",
    "x_news_ai": "Нужен X API/Bearer Token или легальный источник данных X.",
    "youtube_news_ai": "Нужен YouTube Data API/RSS каналов и отдельный парсер видео.",
}

CRITICAL_AGENTS = {"finance_crypto_ai", "politics_government_ai", "security_news_ai", "world_news_ai"}


def audit_news_ai() -> dict[str, object]:
    """Run scripted interview/audit of all news AI agents."""

    report = run_news_agents()
    agents = list(report.get("agents", [])) if isinstance(report, dict) else []
    interviews = [_interview_agent(agent) for agent in agents]
    fake_like = [item for item in interviews if item["verdict"] in {"делает вид", "заглушка"}]
    underbuilt = [item for item in interviews if item["verdict"] in {"недоработан", "частично работает"}]
    working = [item for item in interviews if item["verdict"] == "работает"]
    priority = _priority_actions(interviews)
    grade = _overall_grade(len(working), len(interviews), len(fake_like), len(underbuilt))
    return {
        "status": "ok",
        "auditor": {
            "name": "AI Auditor",
            "role": "Проводит беседу с под-AI и проверяет, кто реально работает, кто заглушка, кто требует доработки.",
            "overall_grade": grade,
            "working": len(working),
            "underbuilt": len(underbuilt),
            "fake_like": len(fake_like),
            "total": len(interviews),
            "summary": _summary(grade, len(working), len(interviews), len(fake_like), len(underbuilt)),
        },
        "interviews": interviews,
        "priority_actions": priority,
        "supervisor": report.get("supervisor", {}) if isinstance(report, dict) else {},
    }


def _interview_agent(agent: dict[str, Any]) -> dict[str, object]:
    agent_id = str(agent.get("id", "unknown"))
    name = str(agent.get("name", "Unknown AI"))
    source_count = int(agent.get("source_count", 0) or 0)
    item_count = int(agent.get("item_count", 0) or 0)
    health = int(agent.get("health_score", 0) or 0)
    credibility = float(agent.get("average_credibility_percent", 0) or 0)
    status = str(agent.get("status", "unknown"))
    needs_real_data = agent_id in REAL_DATA_REQUIRED

    questions = [
        {"q": "Какая твоя зона ответственности?", "a": str(agent.get("responsibility", "Не указана."))},
        {"q": "Сколько источников ты реально контролируешь?", "a": str(source_count)},
        {"q": "Есть ли свежие материалы в текущем цикле?", "a": "да" if item_count else "нет, сейчас только источники/демо-сигналы"},
        {"q": "Можешь ли ты работать без внешних ключей?", "a": "частично" if needs_real_data else "да, через RSS/официальные источники"},
        {"q": "Что мешает тебе работать полноценно?", "a": REAL_DATA_REQUIRED.get(agent_id, "Нужно подключить реальный refresh источников и больше проверок качества.")},
    ]

    verdict = _verdict(agent_id=agent_id, source_count=source_count, item_count=item_count, health=health, credibility=credibility, status=status)
    problems = _problems(agent_id=agent_id, source_count=source_count, item_count=item_count, health=health, credibility=credibility, status=status)
    next_fix = _next_fix(agent_id, verdict)
    return {
        "id": agent_id,
        "name": name,
        "status": status,
        "health_score": health,
        "source_count": source_count,
        "item_count": item_count,
        "average_credibility_percent": credibility,
        "verdict": verdict,
        "problems": problems,
        "next_fix": next_fix,
        "interview": questions,
    }


def _verdict(*, agent_id: str, source_count: int, item_count: int, health: int, credibility: float, status: str) -> str:
    if source_count <= 0:
        return "заглушка"
    if agent_id in REAL_DATA_REQUIRED and item_count <= 0:
        return "делает вид"
    if agent_id in REAL_DATA_REQUIRED:
        return "частично работает"
    if status == "overloaded" or health < 60:
        return "недоработан"
    if item_count <= 0 and agent_id in CRITICAL_AGENTS:
        return "частично работает"
    return "работает"


def _problems(*, agent_id: str, source_count: int, item_count: int, health: int, credibility: float, status: str) -> list[str]:
    problems: list[str] = []
    if source_count <= 0:
        problems.append("Нет назначенных источников.")
    if item_count <= 0:
        problems.append("В текущем цикле нет свежих обработанных материалов.")
    if agent_id in REAL_DATA_REQUIRED:
        problems.append(REAL_DATA_REQUIRED[agent_id])
    if health < 70:
        problems.append("Health ниже желаемого уровня.")
    if credibility < 60:
        problems.append("Средняя достоверность низкая или нет достаточной базы для оценки.")
    if status == "overloaded":
        problems.append("AI перегружен: слишком много источников на один цикл.")
    return problems or ["Критических проблем не найдено."]


def _next_fix(agent_id: str, verdict: str) -> str:
    if agent_id == "telegram_news_ai":
        return "Подключить Telegram bot capture для групп/каналов и allowlist чатов."
    if agent_id == "x_news_ai":
        return "Добавить X API reader через env X_API_BEARER_TOKEN и allowlist аккаунтов."
    if agent_id == "youtube_news_ai":
        return "Добавить YouTube RSS/API reader и отделение мнений от фактов."
    if verdict in {"частично работает", "недоработан"}:
        return "Подключить реальный refresh источников и добавить проверку свежести данных."
    if verdict in {"делает вид", "заглушка"}:
        return "Добавить реальные входные данные или отключить показ как активного AI."
    return "Продолжать мониторинг; добавить live freshness score."


def _priority_actions(interviews: list[dict[str, object]]) -> list[str]:
    actions: list[str] = []
    by_id = {str(item["id"]): item for item in interviews}
    for agent_id in ("telegram_news_ai", "x_news_ai", "youtube_news_ai"):
        item = by_id.get(agent_id)
        if item and item.get("verdict") in {"делает вид", "частично работает", "заглушка"}:
            actions.append(str(item["next_fix"]))
    actions.append("Добавить live freshness score: когда последний раз каждый AI реально обновлял данные.")
    actions.append("Добавить self-test кнопку в Mini App: 'Провести беседу с ИИ'.")
    return actions


def _overall_grade(working: int, total: int, fake_like: int, underbuilt: int) -> str:
    if total <= 0:
        return "FAIL"
    ratio = working / total
    if fake_like:
        return "PARTIAL"
    if ratio >= 0.8 and underbuilt <= 1:
        return "GOOD"
    if ratio >= 0.5:
        return "PARTIAL"
    return "WEAK"


def _summary(grade: str, working: int, total: int, fake_like: int, underbuilt: int) -> str:
    if grade == "GOOD":
        return f"Работает {working}/{total}. Система в целом живая, но нужно продолжать live-проверки."
    if fake_like:
        return f"Работает {working}/{total}, но {fake_like} AI выглядят как активные без реального подключения. Их нужно либо подключить, либо пометить как ожидающие доступ."
    return f"Работает {working}/{total}. Недоработано: {underbuilt}. Нужна доработка источников и freshness score."
