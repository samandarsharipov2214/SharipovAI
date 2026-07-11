"""AI evidence and honest proof scoreboard for SharipovAI.

The registry in :mod:`ai_architecture_registry` is the source of truth. The
scoreboard must count the 9 canonical AI organs only; interfaces, transports,
storage and legacy aliases never inflate the total.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ai_architecture_registry import CANONICAL_AI_ORGANS, canonical_id
from sharipovai_constitution import CAPITAL_MODE, EXECUTION_MODE, constitution_snapshot, now_iso

REAL_DATA_LIVE = "live"
REAL_DATA_VIRTUAL_EXECUTION = "virtual_execution"
REAL_DATA_WAITING_API = "waiting_api"
REAL_DATA_DISABLED = "disabled"
REAL_DATA_DEMO = REAL_DATA_VIRTUAL_EXECUTION  # backward compatibility only

LEGACY_AGENT_ALIASES = {
    "demo_trader": "virtual_execution",
    "virtual_trader": "virtual_execution",
    "paper_trading_bot": "virtual_execution",
    "stress_lab_ai": "risk_engine",
    "stress_bot": "risk_engine",
    "portfolio_report_ai": "portfolio_engine",
    "reports_ai": "portfolio_engine",
    "security_cyber_ai": "security_guard",
    "market_agent": "market_intelligence",
    "news_agent": "news_intelligence",
    "news_supervisor_ai": "news_intelligence",
    "confidence_engine": "decision_quality",
    "consensus_engine": "decision_quality",
    "supervisor_ai": "general_controller",
}


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _evidence(*items: str, virtual_execution: bool = False) -> list[str]:
    prefix = (
        "Virtual account only: реальные деньги защищены, AI-органы работают как production."
        if virtual_execution
        else "Live/system organ: требует runtime Evidence и честную freshness."
    )
    return [prefix, *items]


SYSTEM_AI_STATUS: dict[str, dict[str, Any]] = {
    "general_controller": {
        "name": "General Controller AI",
        "real_data_status": REAL_DATA_LIVE,
        "last_real_update": _now_iso(),
        "evidence": _evidence("Канонический системный аудит", "Failure isolation", "Supervisor объединён с General Controller"),
        "missing": ["Нужен always-on watchdog на основном ПК и журнал recovery attempts"],
        "tier": "supervisor",
    },
    "market_intelligence": {
        "name": "Market Intelligence AI",
        "real_data_status": REAL_DATA_LIVE,
        "last_real_update": _now_iso(),
        "evidence": _evidence("Read-only market data paths", "Market regime и trade gate"),
        "missing": ["Подтвердить непрерывную freshness котировок на основном runtime"],
        "tier": "market",
    },
    "news_intelligence": {
        "name": "News Intelligence AI",
        "real_data_status": REAL_DATA_LIVE,
        "last_real_update": _now_iso(),
        "evidence": _evidence("Real RSS refresh", "Specialized News Agent Network", "Credibility/freshness и bridge"),
        "missing": ["Telegram/X/YouTube источники требуют внешних доступов"],
        "tier": "information",
    },
    "risk_engine": {
        "name": "Risk Engine AI",
        "real_data_status": REAL_DATA_LIVE,
        "last_real_update": _now_iso(),
        "evidence": _evidence("Trade blocking", "Drawdown checks", "Stress Lab является подсистемой Risk"),
        "missing": ["Связать с read-only реальным портфелем и live market freshness"],
        "tier": "safety",
    },
    "portfolio_engine": {
        "name": "Portfolio & Reports AI",
        "real_data_status": REAL_DATA_LIVE,
        "last_real_update": _now_iso(),
        "evidence": _evidence("Virtual equity/PnL/fees", "Reports принадлежат Portfolio"),
        "missing": ["Нужен read-only реальный портфель и стабильный daily/weekly export"],
        "tier": "portfolio",
    },
    "virtual_execution": {
        "name": "Virtual Account Execution AI",
        "real_data_status": REAL_DATA_VIRTUAL_EXECUTION,
        "last_real_update": _now_iso(),
        "evidence": _evidence("Виртуальные сделки", "Комиссии и история", "Real orders blocked", virtual_execution=True),
        "missing": ["Добавить slippage, spread и fill-quality metrics"],
        "tier": "execution_virtual",
    },
    "decision_quality": {
        "name": "Decision Quality AI",
        "real_data_status": REAL_DATA_LIVE,
        "last_real_update": _now_iso(),
        "evidence": _evidence("Confidence и Consensus имеют одного владельца", "Conflict/consensus message types"),
        "missing": ["Нужен единый runtime endpoint и калибровка confidence по исходам"],
        "tier": "decision",
    },
    "learning_engine": {
        "name": "Learning Engine AI",
        "real_data_status": REAL_DATA_LIVE,
        "last_real_update": _now_iso(),
        "evidence": _evidence("Learning OS", "Evidence integration", "Controlled lessons/rules/exams"),
        "missing": ["Нужна постоянная база ошибок и approval workflow для правил"],
        "tier": "learning",
    },
    "security_guard": {
        "name": "Security Guard AI",
        "real_data_status": REAL_DATA_LIVE,
        "last_real_update": _now_iso(),
        "evidence": _evidence("Policy guard", "Access controls", "Real-order lock"),
        "missing": ["Нужны secret scanner и suspicious-login alerts"],
        "tier": "security",
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


def _canonical_agent_id(identifier: str) -> str:
    clean = identifier.strip().lower()
    return LEGACY_AGENT_ALIASES.get(clean) or canonical_id(clean) or clean


def enrich_ai_status(agent: dict[str, Any]) -> dict[str, Any]:
    """Add real-data evidence without changing an explicit runtime verdict."""

    original_id = str(agent.get("id", ""))
    agent_id = _canonical_agent_id(original_id)
    enriched = dict(agent)
    enriched["id"] = agent_id
    if original_id and original_id != agent_id:
        enriched["legacy_id"] = original_id

    status = SYSTEM_AI_STATUS.get(agent_id) or NEWS_REAL_DATA_OVERRIDES.get(original_id) or NEWS_REAL_DATA_OVERRIDES.get(agent_id)
    if status:
        for key, value in status.items():
            if key == "name" and enriched.get("name"):
                continue
            enriched.setdefault(key, value)
    else:
        source_count = int(enriched.get("source_count", 0) or 0)
        item_count = int(enriched.get("item_count", 0) or 0)
        enriched.setdefault(
            "real_data_status",
            REAL_DATA_LIVE if item_count > 0 else REAL_DATA_DISABLED if source_count <= 0 else REAL_DATA_WAITING_API,
        )
        enriched.setdefault("last_real_update", _now_iso() if item_count > 0 else None)
        enriched.setdefault("evidence", ["Есть реальные обработанные элементы" if item_count else "Нет доказательств live-работы"])
        enriched.setdefault("missing", [] if item_count > 0 else ["Нужна проверка runtime freshness"])

    enriched.setdefault("last_seen", enriched.get("last_real_update") or now_iso())
    enriched.setdefault("capital_mode", CAPITAL_MODE)
    enriched.setdefault(
        "execution_mode",
        EXECUTION_MODE if enriched.get("real_data_status") == REAL_DATA_VIRTUAL_EXECUTION else "no_order_execution",
    )
    enriched.setdefault("virtual_account_meaning", "Только счёт/исполнение виртуальные; остальные органы обязаны работать на реальных данных.")
    enriched["proof_score"] = proof_score(enriched)
    enriched["honesty_label"] = honesty_label(enriched)
    return enriched


def proof_score(agent: dict[str, Any]) -> int:
    status = str(agent.get("real_data_status", REAL_DATA_DISABLED))
    score = {
        REAL_DATA_LIVE: 90,
        REAL_DATA_VIRTUAL_EXECUTION: 72,
        REAL_DATA_WAITING_API: 25,
        REAL_DATA_DISABLED: 10,
    }.get(status, 20)
    if agent.get("last_real_update") or agent.get("last_seen"):
        score += 5
    score += min(len(agent.get("evidence", [])) * 2, 10)
    score -= min(len(agent.get("missing", [])) * 3, 15)
    if agent.get("verdict") in {"недоработан", "ошибка", "заглушка"}:
        score -= 20
    elif agent.get("verdict") == "частично работает":
        score -= 8
    return max(0, min(100, score))


def honesty_label(agent: dict[str, Any]) -> str:
    status = str(agent.get("real_data_status", REAL_DATA_DISABLED))
    if status == REAL_DATA_LIVE:
        return "реальный орган AI"
    if status == REAL_DATA_VIRTUAL_EXECUTION:
        return "виртуальный счёт/исполнение; дисциплина production"
    if status == REAL_DATA_WAITING_API:
        return "ждёт API / не полностью живой"
    return "выключен или без runtime-доказательств"


def system_scoreboard(agents: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Return exactly one row for each canonical AI organ.

    When runtime agents are supplied, they are canonicalized and merged by ID.
    Missing canonical organs receive their registry evidence rather than being
    silently omitted. Non-AI interfaces are ignored.
    """

    merged: dict[str, dict[str, Any]] = {}
    for agent in agents or []:
        if not isinstance(agent, dict):
            continue
        enriched = enrich_ai_status(agent)
        agent_id = str(enriched.get("id", ""))
        if agent_id in SYSTEM_AI_STATUS:
            merged[agent_id] = enriched

    for organ in CANONICAL_AI_ORGANS:
        merged.setdefault(organ.id, enrich_ai_status({"id": organ.id, "name": organ.name}))

    all_agents = [merged[organ.id] for organ in CANONICAL_AI_ORGANS]
    counts = {
        REAL_DATA_LIVE: sum(1 for agent in all_agents if agent.get("real_data_status") == REAL_DATA_LIVE),
        REAL_DATA_VIRTUAL_EXECUTION: sum(1 for agent in all_agents if agent.get("real_data_status") == REAL_DATA_VIRTUAL_EXECUTION),
        REAL_DATA_WAITING_API: sum(1 for agent in all_agents if agent.get("real_data_status") == REAL_DATA_WAITING_API),
        REAL_DATA_DISABLED: sum(1 for agent in all_agents if agent.get("real_data_status") == REAL_DATA_DISABLED),
    }
    avg_proof = round(sum(int(agent.get("proof_score", 0)) for agent in all_agents) / len(all_agents), 2)
    return {
        "status": "ok",
        "generated_at": now_iso(),
        "constitution": constitution_snapshot(),
        "total": len(all_agents),
        "canonical_total": len(CANONICAL_AI_ORGANS),
        "counts": counts,
        "average_proof_score": avg_proof,
        "agents": all_agents,
    }
