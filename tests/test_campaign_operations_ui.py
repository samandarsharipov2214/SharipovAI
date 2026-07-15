from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB2 = ROOT / "dashboard" / "static" / "web2"


def test_campaign_operations_assets_are_loaded_and_owned() -> None:
    index = (WEB2 / "index.html").read_text(encoding="utf-8")
    coordinator = (WEB2 / "navigation_coordinator_v23.js").read_text(encoding="utf-8")

    assert 'data-page="campaigns"' in index
    assert "campaign_operations_v36.css?v=36" in index
    assert "campaign_operations_v36.js?v=36" in index
    assert "navigation_coordinator_v23.js?v=36" in index
    assert "const VERSION = 36" in coordinator
    assert "['campaigns', 'campaign_operations_v36.js']" in coordinator


def test_campaign_operations_ui_exposes_required_evidence() -> None:
    source = (WEB2 / "campaign_operations_v36.js").read_text(encoding="utf-8")
    css = (WEB2 / "campaign_operations_v36.css").read_text(encoding="utf-8")

    for marker in (
        "/api/campaigns/operations",
        "/api/campaigns/first-testnet/start",
        "matched_fills",
        "target_fills",
        "orphan_execution_count",
        "duplicate_order_count",
        "unresolved_order_count",
        "actual_fee_total",
        "final_report",
        "I_APPROVE_BOUNDED_TESTNET_SHADOW_CAMPAIGN",
        "10–25 USDT",
        "20 matched fills",
    ):
        assert marker in source
    assert ".campaign36-progress" in css
    assert ".campaign36-integrity" in css
    assert ".campaign36-gate" in css


def test_campaign_ui_has_no_client_side_environment_mutation() -> None:
    source = (WEB2 / "campaign_operations_v36.js").read_text(encoding="utf-8")
    assert "process.env" not in source
    assert "localStorage.setItem" not in source
    assert "runtime flags and does not disable kill switch" in source
