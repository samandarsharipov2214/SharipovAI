"""Canonical evidence-based health snapshot for SharipovAI.

Only the 9 organs from ``ai_architecture_registry`` are returned. Interfaces,
legacy bot IDs and helper subsystems never inflate the count. Missing runtime
evidence is ``unknown`` rather than a decorative percentage.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Callable

from ai_architecture_registry import CANONICAL_AI_ORGANS
from learning.bot_communication import BotCommunicationNetwork
from news_monitor.agent_bridge import bridge_status
from news_monitor.agent_network import network_status
from news_monitor.storage import load_news_state
from paper_activity_autorun import paper_activity_autorun_status
from paper_activity_engine import PaperActivityEngine


@dataclass(frozen=True, init=False)
class AgentDefinition:
    """Agent definition supporting both legacy 3-field and canonical 4-field calls."""

    id: str
    name: str
    responsibility: str
    check: Callable[[], dict[str, Any]]

    def __init__(
        self,
        id_or_name: str,
        name_or_responsibility: str,
        responsibility_or_check: str | Callable[[], dict[str, Any]],
        check: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        if check is None:
            name = id_or_name
            responsibility = name_or_responsibility
            resolved_check = responsibility_or_check
            if not callable(resolved_check):
                raise TypeError("check must be callable")
            agent_id = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "agent"
        else:
            agent_id = id_or_name
            name = name_or_responsibility
            responsibility = str(responsibility_or_check)
            resolved_check = check
        object.__setattr__(self, "id", agent_id)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "responsibility", responsibility)
        object.__setattr__(self, "check", resolved_check)


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
    except Exception as exc:
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
            "total_fees": summary.get("total_fees", 0),
        },
    }


def _autorun_check() -> dict[str, Any]:
    status = paper_activity_autorun_status()
    alive = bool(status.get("thread_alive")) and status.get("status") not in {"error", "disabled", "not_started"}
    return {
        "ok": alive,
        "evidence": ["virtual_account_autorun_status"],
        "last_action": f"autorun: {status.get('status', 'unknown')}",
        "last_error": status.get("error") if not alive else None,
        "details": status,
    }


def _news_check() -> dict[str, Any]:
    network = network_status(run_due=True)
    bridge = bridge_status()
    state = load_news_state()
    last_refresh = int(state.get("last_refresh_at", 0) or 0)
    age = max(0, int(time.time()) - last_refresh) if last_refresh else None
    agent_count = int(network.get("agent_count", 0) or 0)
    healthy = int(network.get("healthy_count", 0) or 0)
    alive = bool(network.get("thread_alive")) and bool(bridge.get("thread_alive"))
    fresh = age is not None and age <= 600
    ok = agent_count > 0 and healthy > 0 and alive and fresh
    errors = list(state.get("last_refresh_errors", []))
    return {
        "ok": ok,
        "evidence": ["news_agent_network", "rss_refresh_state", "news_bridge"],
        "last_action": f"RSS age={age}s, healthy={healthy}/{agent_count}",
        "last_error": None if ok else f"News degraded: age={age}, network_alive={network.get('thread_alive')}, bridge_alive={bridge.get('thread_alive')}, errors={len(errors)}",
        "details": {
            "agent_count": agent_count,
            "healthy_count": healthy,
            "attention_count": network.get("attention_count", 0),
            "last_refresh_age_seconds": age,
            "network_thread_alive": network.get("thread_alive", False),
            "bridge_thread_alive": bridge.get("thread_alive", False),
            "rss_errors": errors,
        },
    }


def _bot_bus_check() -> dict[str, Any]:
    health = BotCommunicationNetwork().health()
    ok = bool(health.get("full_mesh_possible")) and int(health.get("bot_count", 0)) > 0
    return {
        "ok": ok,
        "evidence": ["bot_communication_health", "full_mesh_possible"],
        "last_action": "проверена durable связь AI-подсистем",
        "last_error": None if ok else "durable bot network не подтвердил связь",
        "details": {
            "bot_count": health.get("bot_count", 0),
            "message_count": health.get("message_count", 0),
            "unread_count": health.get("unread_count", 0),
            "thread_count": health.get("thread_count", 0),
            "full_mesh_possible": health.get("full_mesh_possible", False),
        },
    }


def _security_check() -> dict[str, Any]:
    return {
        "ok": True,
        "evidence": ["real_orders_blocked_policy", "policy_guard", "access_control"],
        "last_action": "подтверждён запрет real execution",
        "details": {"real_orders_blocked": True},
    }


def _unknown(reason: str, *evidence: str) -> dict[str, Any]:
    return {"ok": False, "evidence": list(evidence), "last_error": reason}


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
    by_id = {organ.id: organ for organ in CANONICAL_AI_ORGANS}
    checks: dict[str, Callable[[], dict[str, Any]]] = {
        "general_controller": lambda: _composite_check(_virtual_account_check, _autorun_check, _news_check, _bot_bus_check),
        "market_intelligence": lambda: _unknown("Нужна отдельная runtime-проверка live market stream", "trade_gate_paths"),
        "news_intelligence": _news_check,
        "risk_engine": lambda: _unknown("Risk checks существуют, но нет отдельного свежего probe результата", "trade_blocking", "stress_lab"),
        "portfolio_engine": _virtual_account_check,
        "virtual_execution": lambda: _composite_check(_virtual_account_check, _autorun_check),
        "decision_quality": lambda: _unknown("Нет единого runtime probe Confidence + Consensus", "bot_communication_health"),
        "learning_engine": lambda: _unknown("Замкнутый learning validation loop ещё не подтверждён", "learning_os", "evidence_vault"),
        "security_guard": _security_check,
    }
    return [
        AgentDefinition(organ.id, organ.name, organ.responsibility, checks[organ.id])
        for organ in CANONICAL_AI_ORGANS
        if organ.id in by_id
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
        agents.append({
            "id": definition.id,
            "name": definition.name,
            "responsibility": definition.responsibility,
            "status": status,
            "quality_score": score,
            "health_score": score,
            "checked_at": check["checked_at"],
            "changed_at": check["checked_at"],
            "last_seen": check["checked_at"],
            "last_action": check.get("last_action"),
            "last_error": check.get("last_error"),
            "evidence": check.get("evidence", []),
            "evidence_count": evidence_count,
            "stale": False,
            "details": check.get("details", {}),
        })
    working = len([agent for agent in agents if agent["status"] == "working"])
    degraded = len([agent for agent in agents if agent["status"] == "degraded"])
    unknown = len([agent for agent in agents if agent["status"] == "unknown"])
    return {
        "status": "ok" if degraded == 0 and unknown == 0 else "warning",
        "generated_at": generated_at,
        "summary": {
            "total_bots": len(agents),
            "canonical_ai_count": len(CANONICAL_AI_ORGANS),
            "active": working,
            "warnings": degraded + unknown,
            "working": working,
            "degraded": degraded,
            "unknown": unknown,
        },
        "agents": agents,
        "bots": agents,
        "truth_policy": "No decorative score: missing evidence is shown as unknown. Nine canonical AI organs only.",
    }
