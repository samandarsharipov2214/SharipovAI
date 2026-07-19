"""Fail-closed alert projections for scaling and performance evidence."""
from __future__ import annotations

import math
from typing import Any, Mapping


def project_performance_alerts(
    report: Mapping[str, Any], *, drawdown_limit_bps: float = 250.0
) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    month = str(report.get("month") or "unknown")
    drawdown = _finite(report.get("maximum_drawdown_bps"))
    net = _finite(report.get("net_pnl_usdt"))
    fills = _integer(report.get("matched_fill_count"))
    limit = _finite(drawdown_limit_bps)
    if drawdown is None or net is None or fills is None or limit is None or limit < 0:
        return [
            {
                "key": f"phase10:invalid-performance-evidence:{month}",
                "severity": "critical",
                "title": "Performance evidence is invalid",
                "details": {"month": month},
                "delivery": ["dashboard", "telegram", "webhook"],
            }
        ]
    if drawdown < 0 or fills < 0:
        alerts.append(
            {
                "key": f"phase10:negative-risk-evidence:{month}",
                "severity": "critical",
                "title": "Performance evidence contains impossible negative metrics",
                "details": {"month": month},
                "delivery": ["dashboard", "telegram", "webhook"],
            }
        )
        return alerts
    if drawdown > limit:
        alerts.append(
            {
                "key": f"phase10:monthly-drawdown:{month}",
                "severity": "critical",
                "title": "Monthly drawdown limit exceeded",
                "details": {"month": month, "drawdown_bps": drawdown, "limit_bps": limit},
                "delivery": ["dashboard", "telegram", "webhook"],
            }
        )
    if net < 0:
        alerts.append(
            {
                "key": f"phase10:negative-month:{month}",
                "severity": "warning",
                "title": "Negative monthly net PnL",
                "details": {"month": month, "net_pnl_usdt": net},
                "delivery": ["dashboard", "telegram"],
            }
        )
    if fills == 0:
        alerts.append(
            {
                "key": f"phase10:no-evidence:{month}",
                "severity": "warning",
                "title": "Monthly report has no matched fills",
                "details": {"month": month},
                "delivery": ["dashboard"],
            }
        )
    return alerts


def project_activation_alerts(
    activation: Mapping[str, Any], *, now_ms: int
) -> list[dict[str, Any]]:
    activation_id = str(activation.get("activation_id") or "unknown")
    expires = _integer(activation.get("expires_at_ms"))
    now = _integer(now_ms)
    if expires is None or now is None:
        return [
            {
                "key": f"phase10:invalid-scaling-evidence:{activation_id}",
                "severity": "critical",
                "title": "Scaling authority evidence is invalid",
                "details": {"activation_id": activation_id},
                "delivery": ["dashboard", "telegram", "webhook"],
            }
        ]
    if activation.get("status") == "active" and now >= expires:
        return [
            {
                "key": f"phase10:expired-scaling:{activation_id}",
                "severity": "critical",
                "title": "Scaling authority expired",
                "details": {"activation_id": activation_id, "expires_at_ms": expires},
                "delivery": ["dashboard", "telegram", "webhook"],
            }
        ]
    return []


def _finite(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed


__all__ = ["project_activation_alerts", "project_performance_alerts"]
