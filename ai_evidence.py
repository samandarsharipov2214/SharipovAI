"""AI evidence log and real data status scoreboard for SharipovAI.

The goal is to stop self-deception: every AI bot gets a clear data status,
last real update marker, evidence, and next required fix.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

REAL_DATA_LIVE = "live"
REAL_DATA_DEMO = "demo"
REAL_DATA_WAITING_API = "waiting_api"
REAL_DATA_DISABLED = "disabled"


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


SYSTEM_AI_STATUS: dict[str, dict[str, Any]] = {
    "general_controller": {
        "name": "General Controller AI",
        "real_data_status": REAL_DATA_DEMO,
        "last_real_update": None,
        "evidence": ["Есть системный аудит", "Есть supervisor decision", "Есть health/status summary"],
        "missing": ["Нужен периодический cron/self-test", "Нужен журнал действий контролёра"],
        "tier": "supervisor",
    },
    "risk_engine": {
        "name": "Risk Engine AI",
        "real_data_status": REAL_DATA_DEMO,
        "last_real_update": None,
        "evidence": ["Есть demo risk state", "Есть блокировка LIVE по умолчанию", "Есть stress lab"],
        "missing": ["Нужно связать с реальным портфелем", "Нужен журнал причин блокировки"],
        "tier": "safety",
    },
    "demo_trader": {
        "name": "Demo Trader AI",
        "real_data_status": REAL_DATA_DEMO,
        "last_real_update": _now_iso(),
        "evidence": ["Есть demo state", "Есть demo chat", "Есть демо-сделки"],
        "missing": ["Расширить стратегии", "Добавить paper trading метрики"],
        "tier": "execution_demo",
    },
    "exchange_cost_ai": {
        "name": "Exchange Cost AI",
        "real_data_status": REAL_DATA_DEMO,
        "last_real_update": _now_iso(),
        "evidence": ["Есть fee/cost логика", "Есть break-even идея", "LIVE orders заблокированы"],
        "missing": ["Нужен live read-only sync тарифов", "Нужен slippage simulator"],
        "tier": "cost",
    },
    "learning_engine": {
        "name": "Learning Engine AI",
        "real_data_status": REAL_DATA_DEMO,
        "last_real_update": None,
        "evidence": ["Есть skeleton learning summary"],
        "missing": ["Нужна база ошибок", "Нужны уроки", "Нужна автогенерация новых правил"],
        "tier": "learning",
    },
    "stress_lab_ai": {
        "name": "Stress Lab AI",
        "real_data_status": REAL_DATA_DEMO,
        "last_real_update": _now_iso(),
        "evidence": ["Есть stress сценарии", "Есть risk shock simulation"],
        "missing": ["Добавить depeg/flash crash/exchange outage", "Связать со стратегиями"],
        "tier": "safety",
    },
    "security_cyber_ai": {
        "name": "Security/Cyber AI",
        "real_data_status": REAL_DATA_DEMO,
        "last_real_update": None,
        "evidence": ["LIVE trading disabled", "Есть security news sources"],
        "missing": ["Нужен secret scanner", "Нужен suspicious login alert"],
        "tier": "security",
    },
    "telegram_bot_ai": {
        "name": "Telegram Bot AI",
        "real_data_status": REAL_DATA_DEMO,
        "last_real_update": None,
        "evidence": ["Есть telegram_bot.py", "Есть WEBAPP_URL architecture"],
        "missing": ["Нужен production bot self-test", "Нужен capture из allowlist групп"],
        "tier": "interface",
    },
    "mini_app_ui_ai": {
        "name": "Mini App UI AI",
        "real_data_status": REAL_DATA_DEMO,
        "last_real_update": _now_iso(),
        "evidence": ["Есть web dashboard", "Есть live pages", "Есть Mini App JS"],
        "missing": ["Убрать костыли JS", "Добавить встроенную кнопку 'Можно ли торговать?'"],
        "tier": "interface",
    },
}


NEWS_REAL_DATA_OVERRIDES: dict[str, dict[str, Any]] = {
    "telegram_news_ai": {
        "real_data_status": REAL_DATA_WAITING_API,
        "last_real_update": None,
        "missing": ["Нужен Telegram client/bot capture", "Нужен allowlist каналов/групп"],
    },
    "x_news_ai": {
        "real_data_status": REAL_DATA_WAITING_API,
        "last_real_update": None,
        "missing": ["Нужен X API/Bearer Token", "Нужен allowlist аккаунтов"],
    },
    "youtube_news_ai": {
        "real_data_status": REAL_DATA_WAITING_API,
        "last_real_update": None,
        "missing": ["Нужен YouTube RSS/API reader", "Нужна оценка видео/описаний"],
    },
}


def enrich_ai_status(agent: dict[str, Any]) -> dict[str, Any]:
    """Add real data status/evidence to any system or news AI agent."""

    agent_id = str(agent.get("id", ""))
    enriched = dict(agent)
    status = SYSTEM_AI_STATUS.get(agent_id) or NEWS_REAL_DATA_OVERRIDES.get(agent_id)
    if status:
        enriched.update({key: value for key, value in status.items() if key not in {"name"} or not enriched.get("name")})
    else:
        source_count = int(enriched.get("source_count", 0) or 0)
        item_count = int(enriched.get("item_count", 0) or 0)
        enriched.setdefault("real_data_status", REAL_DATA_LIVE if item_count > 0 else REAL_DATA_DEMO if source_count > 0 else REAL_DATA_DISABLED)
        enriched.setdefault("last_real_update", _now_iso() if item_count > 0 else None)
        enriched.setdefault("evidence", ["Есть источники" if source_count else "Нет доказательств live-работы"])
        enriched.setdefault("missing", [] if item_count > 0 else ["Нужна проверка свежести данных"])
    enriched["proof_score"] = proof_score(enriched)
    enriched["honesty_label"] = honesty_label(enriched)
    return enriched


def proof_score(agent: dict[str, Any]) -> int:
    """Compute simple proof score from data status and evidence."""

    status = str(agent.get("real_data_status", REAL_DATA_DISABLED))
    score = {REAL_DATA_LIVE: 90, REAL_DATA_DEMO: 60, REAL_DATA_WAITING_API: 25, REAL_DATA_DISABLED: 10}.get(status, 20)
    if agent.get("last_real_update"):
        score += 5
    score += min(len(agent.get("evidence", [])) * 2, 8)
    score -= min(len(agent.get("missing", [])) * 3, 15)
    return max(0, min(100, score))


def honesty_label(agent: dict[str, Any]) -> str:
    """Return user-facing honesty label."""

    status = str(agent.get("real_data_status", REAL_DATA_DISABLED))
    if status == REAL_DATA_LIVE:
        return "реально живой"
    if status == REAL_DATA_DEMO:
        return "работает в demo"
    if status == REAL_DATA_WAITING_API:
        return "ждёт API / не полностью живой"
    return "выключен или заглушка"


def system_scoreboard(news_agents: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Return honest scoreboard for all known AI bots."""

    system_agents = [enrich_ai_status({"id": agent_id, **data}) for agent_id, data in SYSTEM_AI_STATUS.items()]
    news = [enrich_ai_status(agent) for agent in (news_agents or [])]
    all_agents = system_agents + news
    counts = {
        REAL_DATA_LIVE: sum(1 for agent in all_agents if agent.get("real_data_status") == REAL_DATA_LIVE),
        REAL_DATA_DEMO: sum(1 for agent in all_agents if agent.get("real_data_status") == REAL_DATA_DEMO),
        REAL_DATA_WAITING_API: sum(1 for agent in all_agents if agent.get("real_data_status") == REAL_DATA_WAITING_API),
        REAL_DATA_DISABLED: sum(1 for agent in all_agents if agent.get("real_data_status") == REAL_DATA_DISABLED),
    }
    avg_proof = round(sum(int(agent.get("proof_score", 0)) for agent in all_agents) / len(all_agents), 2) if all_agents else 0
    return {"status": "ok", "total": len(all_agents), "counts": counts, "average_proof_score": avg_proof, "agents": all_agents}
