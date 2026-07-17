from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB2 = ROOT / "dashboard" / "static" / "web2"


def test_phase7_ui_exposes_persistent_alerts_and_actual_private_evidence() -> None:
    source = (WEB2 / "campaign_monitor_v38.js").read_text(encoding="utf-8")
    for contract in (
        "/api/campaigns/operations",
        "/api/campaigns/phase7/monitor",
        "/api/campaigns/phase7/alerts/refresh",
        "actual_fill_count",
        "critical_open_count",
        "document.visibilityState",
        "credentials: 'same-origin'",
        "version: 39",
    ):
        assert contract in source
    api = (ROOT / "dashboard" / "phase7_campaign_api.py").read_text(encoding="utf-8")
    assert '/api/campaigns/phase7/alerts' in api
    assert "CampaignCriticalAlertMonitor" in api


def test_phase7_monitor_ui_is_responsive_and_cache_busted() -> None:
    css = (WEB2 / "campaign_monitor_v38.css").read_text(encoding="utf-8")
    index = (WEB2 / "index.html").read_text(encoding="utf-8")
    assert "@media(max-width:1200px)" in css
    assert "@media(max-width:760px)" in css
    assert "@media(max-width:460px)" in css
    assert "overflow-x:auto" in css
    assert "campaign_monitor_v38.css?v=39" in index
    assert "campaign_monitor_v38.js?v=39" in index
