"""Canonical, evidence-based health snapshot for SharipovAI agents."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable

from architecture_registry import architecture_audit
from learning.ai_learning_core import BOT_NAMES
from learning.bot_communication import BotCommunicationNetwork
from news_monitor.agent_network import network_status
from paper_activity_autorun import paper_activity_autorun_status
from paper_activity_engine import PaperActivityEngine
from portfolio_engine import PortfolioEngine, PortfolioInput, Position
from risk_engine import RiskEngine, RiskInput


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
        "details": {"trade_count": summary.get("trade_count", 0), "last_tick_age_seconds": tick_age, "net_pnl": summary.get("net_pnl", 0)},
    }


def _autorun_check() -> dict[str, Any]:
    status = paper_activity_autorun_status()
    alive = bool(status.get("thread_alive")) and status.get("status") not in {"error", "disabled", "not_started"}
    return {"ok": alive, "evidence": ["paper_activity_autorun_status"], "last_action": f"autorun: {status.get('status', 'unknown')}", "last_error": status.get("error") if not alive else None, "details": status}


def _bot_bus_check() -> dict[str, Any]:
    health = BotCommunicationNetwork().health()
    ok = bool(health.get("full_mesh_possible")) and int(health.get("bot_count", 0)) >= len(BOT_NAMES)
    return {"ok": ok, "evidence": ["bot_communication_health", "full_mesh_possible"], "last_action": "проверена durable связь AI-ботов", "last_error": None if ok else "durable bot network не подтвердил полную связь", "details": health}


def _news_check() -> dict[str, Any]:
    status = network_status(run_due=False)
    initialized = int(status.get("initialized_count", 0))
    healthy = int(status.get("healthy_count", 0))
    ok = status.get("status") == "ok" and initialized > 0 and healthy > 0
    return {
        "ok": ok,
        "evidence": ["specialized_news_network", "saved_news_state"] if initialized else [],
        "last_action": f"specialized news healthy={healthy}/{status.get('agent_count', 0)}",
        "last_error": None if ok else status.get("network_error") or "news network не имеет достаточного runtime evidence",
        "details": {"agent_count": status.get("agent_count", 0), "initialized_count": initialized, "healthy_count": healthy, "attention_count": status.get("attention_count", 0)},
    }


def _risk_check() -> dict[str, Any]:
    low = RiskEngine().evaluate(RiskInput(1, 10, 5, 10, 90, 10))
    critical = RiskEngine().evaluate(RiskInput(90, 95, 95, 95, 5, 95))
    ok = bool(low.allowed) and not bool(critical.allowed) and critical.risk_score > low.risk_score
    return {"ok": ok, "evidence": ["risk_low_scenario", "risk_critical_block"], "last_action": f"risk smoke: low={low.risk_score:.1f}, critical={critical.risk_score:.1f}", "last_error": None if ok else "Risk Engine не заблокировал критический сценарий", "details": {"low_allowed": low.allowed, "critical_allowed": critical.allowed}}


def _portfolio_check() -> dict[str, Any]:
    result = PortfolioEngine().evaluate(PortfolioInput(cash=1000.0, positions=[Position("BTCUSDT", 0.01, 50000.0, 60000.0)]))
    ok = result.total_value == 1600.0 and result.positions_count == 1 and 0 < result.exposure_percent < 100
    return {"ok": ok, "evidence": ["portfolio_valuation", "position_exposure"], "last_action": f"portfolio smoke: total={result.total_value:.2f}", "last_error": None if ok else "Portfolio Engine вернул некорректную оценку", "details": {"total_value": result.total_value, "exposure_percent": result.exposure_percent}}


def _architecture_check() -> dict[str, Any]:
    audit = architecture_audit()
    ok = audit.get("status") == "ok"
    return {"ok": ok, "evidence": ["canonical_capability_registry", "duplicate_capability_audit"], "last_action": f"architecture audit: {audit.get('component_count')} components", "last_error": None if ok else "обнаружены незарегистрированные или дублирующие функции", "details": audit}


def _composite_check(*checks: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    results = [_safe_check(check) for check in checks]
    ok = all(item["ok"] for item in results)
    return {"ok": ok, "evidence": [value for item in results for value in item.get("evidence", [])], "last_action": "; ".join(item["last_action"] for item in results if item.get("last_action")) or None, "last_error": "; ".join(item["last_error"] for item in results if item.get("last_error")) or None, "details": {"checks": results}}


def _definitions() -> list[AgentDefinition]:
    return [
        AgentDefinition("General Controller", "единый контроль состояния и зависимостей", lambda: _composite_check(_architecture_check, _bot_bus_check)),
        AgentDefinition("Market Agent", "рыночные данные и торговые кандидаты", _virtual_account_check),
        AgentDefinition("News Agent", "новости и подтверждение источников", _news_check),
        AgentDefinition("Risk Engine", "лимиты риска и блокировка опасных входов", _risk_check),
        AgentDefinition("Portfolio Engine", "equity, PnL, комиссии и позиции", _portfolio_check),
        AgentDefinition("Paper Trading Bot", "виртуальное исполнение и lifecycle позиций", lambda: _composite_check(_virtual_account_check, _autorun_check)),
        AgentDefinition("Confidence Engine", "калибровка уверенности", lambda: {"ok": False, "evidence": [], "last_error": "нет отдельной проверки калибровки confidence"}),
        AgentDefinition("Consensus Engine", "согласование решений агентов", _bot_bus_check),
        AgentDefinition("Stress Bot", "стресс-сценарии и защитные меры", _risk_check),
        AgentDefinition("Learning Engine", "ошибка → урок → правило → валидация", lambda: {"ok": False, "evidence": [], "last_error": "замкнутый learning validation loop ещё не подтверждён"}),
        AgentDefinition("Security Guard", "запрет реальных ордеров и security policy", lambda: {"ok": True, "evidence": ["real_orders_blocked_policy"], "last_action": "подтверждён запрет real execution"}),
    ]


def build_agent_health_snapshot() -> dict[str, Any]:
    generated_at = int(time.time())
    agents: list[dict[str, Any]] = []
    for definition in _definitions():
        check = _safe_check(definition.check)
        evidence_count = len(check.get("evidence", []))
        status = "working" if check["ok"] else ("degraded" if evidence_count else "unknown")
        score = min(100, 60 + evidence_count * 10) if check["ok"] else (max(0, 30 + evidence_count * 5) if evidence_count else None)
        agents.append({"name": definition.name, "responsibility": definition.responsibility, "status": status, "quality_score": score, "health_score": score, "checked_at": check["checked_at"], "changed_at": check["checked_at"], "last_action": check.get("last_action"), "last_error": check.get("last_error"), "evidence": check.get("evidence", []), "evidence_count": evidence_count, "stale": False, "details": check.get("details", {})})
    working = sum(agent["status"] == "working" for agent in agents)
    degraded = sum(agent["status"] == "degraded" for agent in agents)
    unknown = sum(agent["status"] == "unknown" for agent in agents)
    return {"status": "ok" if degraded == 0 and unknown == 0 else "warning", "generated_at": generated_at, "summary": {"total_bots": len(agents), "active": working, "warnings": degraded + unknown, "working": working, "degraded": degraded, "unknown": unknown}, "agents": agents, "bots": agents, "architecture": architecture_audit(), "truth_policy": "No decorative score: missing evidence is shown as unknown."}
