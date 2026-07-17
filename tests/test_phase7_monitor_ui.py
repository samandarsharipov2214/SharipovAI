from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "dashboard" / "phase7_campaign_api.py"
JS = ROOT / "dashboard" / "static" / "web2" / "campaign_monitor_v38.js"
CSS = ROOT / "dashboard" / "static" / "web2" / "campaign_monitor_v38.css"
INDEX = ROOT / "dashboard" / "static" / "web2" / "index.html"


def test_phase7_monitor_api_is_admin_protected() -> None:
    source = API.read_text(encoding="utf-8")
    for route in (
        "/api/campaigns/phase7/monitor",
        "/api/campaigns/phase7/refresh",
        "/api/campaigns/phase7/fills",
        "/api/campaigns/phase7/report",
    ):
        assert route in source
    assert source.count("require_admin(request)") >= 4
    assert '"runtime_flags_changed": False' in source
    assert '"mainnet_enabled": False' in source


def test_phase7_ui_polls_live_private_evidence() -> None:
    source = JS.read_text(encoding="utf-8")
    index = INDEX.read_text(encoding="utf-8")

    assert "const POLL_MS = 3000" in source
    assert "/api/campaigns/operations" in source
    assert "/api/campaigns/phase7/monitor" in source
    assert "actual_fills" in source
    assert "actual_fee_total" in source
    assert "heartbeat_stale" in source
    assert "Campaign Operations API/CLI" in source
    assert "campaign_monitor_v38.css?v=38" in index
    assert "campaign_monitor_v38.js?v=38" in index
    assert CSS.exists()
