from pathlib import Path

from observability.phase10_performance_alerts import project_activation_alerts, project_performance_alerts


ROOT = Path(__file__).resolve().parents[1]


def test_monthly_drawdown_projects_critical_delivery():
    alerts = project_performance_alerts({"month": "2026-07", "maximum_drawdown_bps": 300, "net_pnl_usdt": -1, "matched_fill_count": 10})
    critical = next(item for item in alerts if item["severity"] == "critical")
    assert critical["delivery"] == ["dashboard", "telegram", "webhook"]


def test_expired_activation_projects_critical_alert():
    alerts = project_activation_alerts({"activation_id": "a1", "status": "active", "expires_at_ms": 100}, now_ms=101)
    assert alerts[0]["key"] == "phase10:expired-scaling:a1"


def test_dashboard_mounts_phase10_assets():
    html = (ROOT / "dashboard/static/web2/index.html").read_text(encoding="utf-8")
    js = (ROOT / "dashboard/static/web2/phase10_scaling_performance_v42.js").read_text(encoding="utf-8")
    assert "data-phase10-scaling-performance" in html
    assert "phase10_scaling_performance_v42.js" in html
    assert "/api/performance/phase10/overview" in js
    assert "Mainnet remains unavailable" in js


def test_constitution_preserves_mainnet_lock():
    text = (ROOT / "CONSTITUTION.md").read_text(encoding="utf-8")
    assert "phase10-controlled-scaling-performance-v13" in text
    assert "Mainnet execution remains compiled out" in text
    assert "I_APPROVE_CONTROLLED_TESTNET_NOTIONAL_SCALING" in text
