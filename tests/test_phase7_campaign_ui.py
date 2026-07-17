from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB2 = ROOT / "dashboard" / "static" / "web2"


def test_campaign_operations_ui_exposes_live_operations_and_alert_controls() -> None:
    source = (WEB2 / "campaign_operations_v36.js").read_text(encoding="utf-8")
    for contract in (
        "/api/campaigns/operations",
        "/api/campaigns/alerts/tick",
        "/api/campaigns/first-testnet/start",
        "/api/campaigns/orchestrator/tick",
        "/api/campaigns/schedules",
        "campaign36CampaignSelect",
        "campaign36AutoRefresh",
        "document.visibilityState",
        "real private fills",
    ):
        assert contract in source
    assert "innerHTML" in source
    assert "credentials: 'same-origin'" in source


def test_campaign_operations_ui_is_responsive_and_cache_busted() -> None:
    css = (WEB2 / "campaign_operations_v36.css").read_text(encoding="utf-8")
    index = (WEB2 / "index.html").read_text(encoding="utf-8")
    assert "@media(max-width:1100px)" in css
    assert "@media(max-width:760px)" in css
    assert "overflow-x:auto" in css
    assert "campaign_operations_v36.css?v=38" in index
    assert "campaign_operations_v36.js?v=38" in index
