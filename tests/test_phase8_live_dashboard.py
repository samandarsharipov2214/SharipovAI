from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIVE = ROOT / "campaigns" / "phase8_live.py"
API = ROOT / "dashboard" / "phase8_campaign_api.py"
ALERTS = ROOT / "observability" / "phase8_alerts.py"
WEB = ROOT / "dashboard" / "static" / "web2"
INDEX = WEB / "index.html"


def test_phase8_live_view_is_versioned_and_read_only() -> None:
    source = LIVE.read_text(encoding="utf-8")
    for token in (
        "Phase8CampaignLiveView",
        "sequence",
        "material_sha256",
        "changed_since",
        "campaign_drawdown_exceeded",
        "phase8_campaign_live_events",
        '"runtime_flags_changed": False',
        '"mainnet_enabled": False',
    ):
        assert token in source


def test_phase8_api_is_admin_protected_and_read_only() -> None:
    source = API.read_text(encoding="utf-8")
    assert source.count("require_admin(request)") >= 3
    assert "/api/campaigns/phase8/live" in source
    assert "/api/campaigns/phase8/analysis/{campaign_id}" in source
    assert "/api/campaigns/phase8/recommendation/{campaign_id}" in source
    assert "@app.post" not in source
    assert '"automatic_promotion": False' in source
    assert "Phase8RiskAlertMonitor" in source


def test_phase8_persists_drawdown_and_recommendation_alerts() -> None:
    source = ALERTS.read_text(encoding="utf-8")
    for token in (
        "Phase8RiskAlertService",
        "Phase8RiskAlertMonitor",
        "phase8_risk_alerts",
        "campaign_drawdown_exceeded",
        "campaign_recommendation_reject",
        "campaign_recommendation_hold",
        "phase8_analysis_failure",
        "resolved",
    ):
        assert token in source


def test_phase8_dashboard_polls_once_per_second_and_is_additive() -> None:
    client = (WEB / "campaign_intelligence_client_v40.js").read_text(encoding="utf-8")
    view = (WEB / "campaign_intelligence_view_v40.js").read_text(encoding="utf-8")
    index = INDEX.read_text(encoding="utf-8")
    assert "setInterval" in client and "1000" in client
    assert "since_sequence" in client
    assert "phase8data" in client and "phase8data" in view
    assert "#content .campaign36-shell" in view
    assert "phase8IntelligencePanel" in view
    assert "Drawdown" in view
    assert "Recommendation" in view
    assert "phase8_risk_alerts" in view
    assert "campaign_intelligence_client_v40.js?v=40" in index
    assert "campaign_intelligence_view_v40.js?v=40" in index
    assert "campaign_intelligence_v40.css?v=40" in index
