"""Phase 9 alert projection for campaign quality and scaling blockers."""
from __future__ import annotations

from typing import Any, Mapping, Sequence


def phase9_alerts(report: Mapping[str, Any] | None, plans: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    if report:
        risk = report.get("risk_metrics") if isinstance(report.get("risk_metrics"), Mapping) else {}
        if float(risk.get("maximum_drawdown_bps") or 0.0) > 250.0:
            alerts.append(_alert("critical", "campaign_drawdown_breach", "Maximum campaign drawdown exceeded 250 bps."))
        profit_factor = risk.get("profit_factor")
        if profit_factor != "infinity" and float(profit_factor or 0.0) < 1.0:
            alerts.append(_alert("warning", "campaign_profit_factor_below_one", "Campaign gross losses exceeded gross profits."))
        if report.get("source_failed_gates"):
            alerts.append(_alert("critical", "campaign_source_gates_failed", "Phase 8 source gates are not clean."))
    for plan in plans:
        if str(plan.get("status") or "") == "blocked":
            alerts.append(_alert("warning", "scaling_plan_blocked", "Scaling preparation is blocked by one or more gates."))
    return alerts


def _alert(severity: str, code: str, message: str) -> dict[str, Any]:
    return {"severity": severity, "code": code, "message": message, "telegram_eligible": severity == "critical", "webhook_eligible": severity in {"critical", "warning"}}


__all__ = ["phase9_alerts"]
