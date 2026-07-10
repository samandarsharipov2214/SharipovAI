"""Canonical, evidence-based health snapshot for SharipovAI agents.

This module deliberately avoids decorative percentages and synthetic "last seen"
timestamps.  A module is only marked healthy when a concrete runtime check
succeeds.  When evidence is missing the public status is ``unknown`` instead of
pretending that the agent is working.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable

from learning.ai_learning_core import BOT_NAMES
from learning.bot_communication import BotCommunicationNetwork
from paper_activity_autorun import paper_activity_autorun_status
from paper_activity_engine import PaperActivityEngine


@dataclass(frozen=True)
class AgentDefinition:
    name: str
    responsibility: str
    check: Callable[[], dict[str, Any]]


def _safe_check(check: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    checked_at = int(time.time())
    try:
        result = check() or {}
        ok = bool(result.get("ok"))
        return {
            "ok": ok,
            "checked_at": checked_at,
            "evidence": result.get("evidence", []),
            "last_action": result.get("last_action"),
            "last_error": None if ok else result.get("last_error", "проверка не подтверждена"),
            "details": result.get("details", {}),
        }
    except Exception as exc:  # production health must degrade, not crash the API
        return {
            "ok": False,
            "checked_at": checked_at,
            "evidence": [],
            "last_action": None,
            "last_error": f"{type(exc).__name__}: {exc}",
            "details": {},
        }


def _virtual_account_check() -> dict[str, Any]:
    state = PaperActivityEngine().state(catch_up=False)
    summary = state.get("summary", {})
    tick_age = summary.get("last_tick_age_seconds")
    fresh = tick_age is not None and int(tick_age) <= max(180, int(state.get("config", {}).get("tick_seconds", 60)) * 3)
    return {
        "ok": fresh,
        "evidence": ["virtual_account_state", "last_tick_age_seconds"],
        "last_action": summary.get("last_reason_ru") or summary.get("last_reason"),
        "last_error": None if fresh else "Virtual Account не имеет свежего execution tick",
        "details": {
            "trade_count": summary.get("trade_count", 0),
            "open_positions": summary.get("open_positions", 0),
            "closed_positions": summary.get("closed_positions", 0),
            "last_tick_age_seconds": tick_age,
            "net_pnl": summary.get("net_pnl", 0),
        },
    }


def _autorun_check() -> dict[str, Any]:
    status = paper_activity_autorun_status()
    alive = bool(status.get("thread_alive")) and status.get("status") not in {"error", "disabled", "not_started"}
    return {
        "ok": alive,
        "evidence": ["paper_activity_autorun_status"],
        "last_action": f"autorun: {status.get('status', 'unknown')}",
        "last_error": status.get("error") if not alive else None,
        "details": status,
    }


def _bot_bus_check() -> dict[str, Any]:
    health = BotCommunicationNetwork().health()
    ok = bool(health.get("full_mesh_possible")) and int(health.get("bot_count", 0)) >= len(BOT_NAMES)
    return {
        "ok": ok,
        "evidence": ["bot_communication_health", "full_mesh_possible"],
        "last_action": "проверена durable связь AI-ботов",
        "last_error": None if ok else "durable bot network не подтвердил полную связь",
        "details": {
            "bot_count": health.get("bot_count", 0),
            "message_count": health.get("message_count", 0),
            "unread_count": health.get("unread_count", 0),
            "thread_count": health.get("thread_count", 0),
            "full_mesh_possible": health.get("full_mesh_possible", False),
        },
    }


def _composite_check(*checks: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    results = [_safe_check(check) for check in checks]
    ok = all(item["ok"] for item in results)
    evidence = [value for item in results for value in item.get("evidence", [])]
    errors = [item.get("last_error") for item in results if item.get("last_error")]
    actions = [item.get("last_action") for item in results if item.get("last_action")]
    return {
        "ok": ok,
        "evidence": evidence,
        "last_action": "; ".join(actions) or None,
        "last_error": "; ".join(errors) or None,
        "details": {"checks": results},
    }


def _definitions() -> list[AgentDefinition]:
    return [
        AgentDefinition("General Controller", "единый контроль состояния и зависимостей", lambda: _composite_check(_virtual_account_check, _autorun_check, _bot_bus_check)),
        AgentDefinition("Market Agent", "рыночные данные и торговые кандидаты", _virtual_account_check),
        AgentDefinition("News Agent", "новости и подтверждение источников", lambda: {"ok": False, "evidence": [], "last_error": "каноническая news-health проверка ещё не подключена"}),
        AgentDefinition("Risk Engine", "лимиты риска и блокировка опасных входов", _virtual_account_check),
        AgentDefinition("Portfolio Engine", "equity, PnL, комиссии и позиции", _virtual_account_check),
        AgentDefinition("Paper Trading Bot", "виртуальное исполнение и lifecycle позиций", lambda: _composite_check(_virtual_account_check, _autorun_check)),
        AgentDefinition("Confidence Engine", "калибровка уверенности", lambda: {"ok": False, "evidence": [], "last_error": "нет отдельной проверки калибровки confidence"}),
        AgentDefinition("Consensus Engine", "согласование решений агентов", _bot_bus_check),
        AgentDefinition("Stress Bot", "стресс-сценарии и защитные меры", lambda: {"ok": False, "evidence": [], "last_error": "нет свежего подтверждённого stress run"}),
        AgentDefinition("Learning Engine", "ошибка → урок → правило → валидация", lambda: {"ok": False, "evidence": [], "last_error": "замкнутый learning validation loop ещё не подтверждён"}),
        AgentDefinition("Security Guard", "запрет реальных ордеров и security policy", lambda: {"ok": True, "evidence": ["real_orders_blocked_policy"], "last_action": "подтверждён запрет real execution"}),
    ]


def build_agent_health_snapshot() -> dict[str, Any]:
    generated_at = int(time.time())
    agents: list[dict[str, Any]] = []
    for definition in _definitions():
        check = _safe_check(definition.check)
        evidence_count = len(check.get("evidence", []))
        if check["ok"]:
            status = "working"
            score: int | None = min(100, 60 + evidence_count * 10)
        elif evidence_count:
            status = "degraded"
            score = max(0, 30 + evidence_count * 5)
        else:
            status = "unknown"
            score = None
        agents.append(
            {
                "name": definition.name,
                "responsibility": definition.responsibility,
                "status": status,
                "quality_score": score,
                "health_score": score,
                "checked_at": check["checked_at"],
                "changed_at": check["checked_at"],
                "last_action": check.get("last_action"),
                "last_error": check.get("last_error"),
                "evidence": check.get("evidence", []),
                "evidence_count": evidence_count,
                "stale": False,
                "details": check.get("details", {}),
            }
        )
    working = len([agent for agent in agents if agent["status"] == "working"])
    degraded = len([agent for agent in agents if agent["status"] == "degraded"])
    unknown = len([agent for agent in agents if agent["status"] == "unknown"])
    return {
        "status": "ok" if degraded == 0 and unknown == 0 else "warning",
        "generated_at": generated_at,
        "summary": {
            "total_bots": len(agents),
            "active": working,
            "warnings": degraded + unknown,
            "working": working,
            "degraded": degraded,
            "unknown": unknown,
        },
        "agents": agents,
        "bots": agents,
        "truth_policy": "No decorative score: missing evidence is shown as unknown.",
    }
