from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_phase8_dashboard_and_api_contracts() -> None:
    api = (ROOT / "dashboard" / "phase8_campaign_api.py").read_text(encoding="utf-8")
    js = (ROOT / "dashboard" / "static" / "web2" / "campaign_analysis_v40.js").read_text(encoding="utf-8")
    css = (ROOT / "dashboard" / "static" / "web2" / "campaign_analysis_v40.css").read_text(encoding="utf-8")
    index = (ROOT / "dashboard" / "static" / "web2" / "index.html").read_text(encoding="utf-8")
    for route in (
        "/api/campaigns/phase8/analyze/{campaign_id}",
        "/api/campaigns/phase8/analysis/{campaign_id}",
        "/api/campaigns/phase8/analyses",
    ):
        assert route in api
    assert "/api/campaigns/phase7/monitor" in js
    assert "document.visibilityState" in js
    assert "credentials:'same-origin'" in js
    assert "@media(max-width:720px)" in css
    assert "campaign_analysis_v40.css?v=40" in index
    assert "campaign_analysis_v40.js?v=40" in index
