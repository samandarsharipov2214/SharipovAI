"""AI evidence log and real data status scoreboard for SharipovAI.

The goal is to stop self-deception: every AI bot gets a clear data status,
last real update marker, evidence, next required fix, and paper-realism
capital discipline. Demo/paper is not a toy; it is a safety wrapper around
serious training.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sharipovai_constitution import constitution_snapshot, now_iso

REAL_DATA_LIVE = "live"
REAL_DATA_DEMO = "demo"
REAL_DATA_WAITING_API = "waiting_api"
REAL_DATA_DISABLED = "disabled"


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _paper_evidence(*items: str) -> list[str]:
    return ["Paper-realism: demo защищает реальные деньги, но AI считает риск как настоящий.", *items]


SYSTEM_AI_STATUS: dict[str, dict[str, Any]] = {
    "general_controller": {
        "name": "General Controller AI",
        "real_data_status": REAL_DATA_DEMO,
        "last_real_update": _now_iso(),
        "evidence": _paper_evidence("Есть системный аудит", "Есть supervisor decision", "Есть health/status summary", "Есть last_seen/last_action через /api/ai-bots"),
        "missing": ["Нужен периодический cron/self-test для полностью автономного цикла"],
        "tier": "supervisor",
    },
    "risk_engine": {
        "name": "Risk Engine AI",
        "real_data_status": REAL_DATA_DEMO,
        "last_real_update": _now_iso(),
        "evidence": _paper_evidence("Есть risk state", "Есть блокировка LIVE по умолчанию", "Есть stress lab", "Риск считается как при реальном капитале"),
        "missing": ["Нужно связать с реальным read-only портфелем"],
        "tier": "safety",
    },
    "demo_trader": {
        "name": "Paper Realism Trader AI",
        "real_data_status": REAL_DATA_DEMO,
        "last_real_update": _now_iso(),
        "evidence": _paper_evidence("Есть paper state", "Есть paper chat", "Есть paper-сделки с комиссиями и уроками"),
        "missing": ["Расширить стратегии", "Добавить paper trading метрики по времени"],
        "tier": "execution_paper",
    },
    "exchange_cost_ai": {
        "name": "Exchange Cost AI",
        "real_data_status": REAL_DATA_DEMO,
        "last_real_update": _now_iso(),
        "evidence": _paper_evidence("Есть fee/cost логика", "Есть break-even идея", "LIVE orders заблокированы"),
        "missing": ["Нужен live read-only sync тарифов", "Нужен slippage simulator"],
        "tier": "cost",
    },
    "learning_engine": {
        "name": "Learning Engine AI",
        "real_data_status": REAL_DATA_DEMO,
        "last_real_update": _now_iso(),
        "evidence": _paper_evidence("Есть learning summary", "Paper-ошибки должны считаться реальными уроками", "Есть Evidence Vault integration"),
        "missing": ["Нужна более богатая база ошибок", "Нужна автогенерация новых правил"],
        "tier": "learning",
    },
    "stress_lab_ai": {
        "name": "Stress Lab AI",
        "real_data_status": REAL_DATA_DEMO,
        "last_real_update": _now_iso(),
        "evidence": _paper_evidence("Есть stress сценарии", "Есть risk shock simulation", "Есть prevented_loss_amount"),
        "missing": ["Добавить depeg/flash crash/exchange outage", "Связать со стратегиями"],
        "tier": "safety",
    },
    "security_cyber_ai": {
        "name": "Security/Cyber AI",
        "real_data_status": REAL_DATA_DEMO,
        "last_real_update": _now_iso(),
        "evidence": _paper_evidence("LIVE trading disabled", "Есть security news sources", "Реальные ордера запрещены без ручного разрешения"),
        "missing": ["Нужен secret scanner", "Нужен suspicious login alert"],
        "tier": "security",
    },
    "telegram_bot_ai": {
        "name": "Telegram Bot AI",
        "real_data_status": REAL_DATA_DEMO,
        "last_real_update": _now_iso(),
        "evidence": _paper_evidence("Есть telegram_bot.py", "Есть webhook architecture", "Есть paper-realism ответы в /start /status /trade"),
        "missing": ["Нужен production webhook self-test с историей последних ошибок"],
        "tier": "interface",
    },
    "mini_app_ui_ai": {
        "name": "Mini App UI AI",
        "real_data_status": REAL_DATA_DEMO,
        "last_real_update": _now_iso(),
        "evidence": _paper_evidence("Есть web dashboard", "Есть live freshness labels", "Убраны fake 00:00/00:01 timestamps"),
        "missing": ["Добавить встроенную кнопку 'Можно ли торговать?' с Evidence Vault replay"],
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
    enriched.setdefault("last_seen", enriched.get("last_real_update") or now_iso())
    enriched.setdefault("capital_mode", "paper_realism" if enriched.get("real_data_status") == REAL_DATA_DEMO else "live" if enriched.get("real_data_status") == REAL_DATA_LIVE else "not_ready")
    enriched.setdefault("demo_meaning", "Если статус demo/paper, это не игрушка: риск и ошибки считаются как тренировка реального капитала.")
    enriched["proof_score"] = proof_score(enriched)
    enriched["honesty_label"] = honesty_label(enriched)
    return enriched


def proof_score(agent: dict[str, Any]) -> int:
    """Compute simple proof score from data status and evidence."""

    status = str(agent.get("real_data_status", REAL_DATA_DISABLED))
    score = {REAL_DATA_LIVE: 90, REAL_DATA_DEMO: 68, REAL_DATA_WAITING_API: 25, REAL_DATA_DISABLED: 10}.get(status, 20)
    if agent.get("last_real_update") or agent.get("last_seen"):
        score += 5
    score += min(len(agent.get("evidence", [])) * 2, 10)
    score -= min(len(agent.get("missing", [])) * 3, 15)
    return max(0, min(100, score))


def honesty_label(agent: dict[str, Any]) -> str:
    """Return user-facing honesty label."""

    status = str(agent.get("real_data_status", REAL_DATA_DISABLED))
    if status == REAL_DATA_LIVE:
        return "реально живой"
    if status == REAL_DATA_DEMO:
        return "paper-realism: деньги защищены, риск считается серьёзно"
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
    return {
        "status": "ok",
        "generated_at": now_iso(),
        "constitution": constitution_snapshot(),
        "total": len(all_agents),
        "counts": counts,
        "average_proof_score": avg_proof,
        "agents": all_agents,
    }
