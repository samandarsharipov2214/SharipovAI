"""Phase 10 persistent performance alert projections."""
from __future__ import annotations

from typing import Any, Mapping


def project_performance_alerts(report: Mapping[str, Any], *, drawdown_limit_bps: float = 250.0) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    month = str(report.get("month") or "unknown")
    drawdown = float(report.get("maximum_drawdown_bps") or 0.0)
    net = float(report.get("net_pnl_usdt") or 0.0)
    fills = int(report.get("matched_fill_count") or 0)
    if drawdown > drawdown_limit_bps:
        alerts.append({"key": f"phase10:monthly-drawdown:{month}", "severity": "critical", "title": "Monthly drawdown limit exceeded", "details": {"month": month, "drawdown_bps": drawdown, "limit_bps": drawdown_limit_bps}, "delivery": ["dashboard", "telegram", "webhook"]})
    if net < 0:
        alerts.append({"key": f"phase10:negative-month:{month}", "severity": "warning", "title": "Negative monthly net PnL", "details": {"month": month, "net_pnl_usdt": net}, "delivery": ["dashboard", "telegram"]})
    if fills == 0:
        alerts.append({"key": f"phase10:no-evidence:{month}", "severity": "warning", "title": "Monthly report has no matched fills", "details": {"month": month}, "delivery": ["dashboard"]})
    return alerts


def project_activation_alerts(activation: Mapping[str, Any], *, now_ms: int) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    activation_id = str(activation.get("activation_id") or "unknown")
    if activation.get("status") == "active" and now_ms >= int(activation.get("expires_at_ms") or 0):
        alerts.append({"key": f"phase10:expired-scaling:{activation_id}", "severity": "critical", "title": "Scaling authority expired", "details": {"activation_id": activation_id}, "delivery": ["dashboard", "telegram", "webhook"]})
    return alerts


__all__ = ["project_activation_alerts", "project_performance_alerts"]
