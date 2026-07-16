from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB2 = ROOT / "dashboard" / "static" / "web2"


def test_campaign_operations_assets_are_loaded_and_owned_by_coordinator() -> None:
    index = (WEB2 / "index.html").read_text(encoding="utf-8")
    coordinator = (WEB2 / "navigation_coordinator_v23.js").read_text(encoding="utf-8")

    assert 'data-page="campaigns"' in index
    assert "campaign_operations_v36.css" in index
    assert "campaign_operations_v36.js" in index
    assert "campaign_decision_v37.css" in index
    assert "campaign_decision_v37.js" in index
    assert "navigation_coordinator_v23.js" in index
    assert "['campaigns', 'campaign_operations_v36.js']" in coordinator


def test_campaign_operations_ui_exposes_full_operator_lifecycle() -> None:
    source = (WEB2 / "campaign_operations_v36.js").read_text(encoding="utf-8")
    css = (WEB2 / "campaign_operations_v36.css").read_text(encoding="utf-8")

    for marker in (
        "/api/campaigns/operations",
        "/api/campaigns/first-testnet/start",
        "/api/campaigns/schedules",
        "/api/campaigns/orchestrator/tick",
        "/run",
        "/promotion-report",
        "matched_fills",
        "target_fills",
        "remaining_fills",
        "orphan_execution_count",
        "duplicate_order_count",
        "unresolved_order_count",
        "actual_fee_total",
        "final_report",
        "I_APPROVE_BOUNDED_TESTNET_SHADOW_CAMPAIGN",
        "10–25 USDT",
        "20 matched fills",
        "setInterval",
        "REFRESH_MS",
    ):
        assert marker in source
    assert ".campaign36-progress" in css
    assert ".campaign36-integrity" in css
    assert ".campaign36-gate" in css


def test_campaign_operations_mutations_refresh_canonical_snapshot() -> None:
    source = (WEB2 / "campaign_operations_v36.js").read_text(encoding="utf-8")

    assert "async function mutate" in source
    assert "await action()" in source
    assert "await load({ quiet: true })" in source
    assert "credentials: 'same-origin'" in source
    assert "cache: 'no-store'" in source


def test_manual_decision_panel_requires_final_report_evidence_and_exact_token() -> None:
    source = (WEB2 / "campaign_decision_v37.js").read_text(encoding="utf-8")
    css = (WEB2 / "campaign_decision_v37.css").read_text(encoding="utf-8")

    for marker in (
        "/api/campaigns/operations",
        "/decision",
        "approval_token",
        "eligible_for_approval",
        "evidence_sha256",
        "Immutable decision saved",
        "Причина решения",
        "Exact approval/rejection token",
        "не включает Testnet/Mainnet",
    ):
        assert marker in source
    assert ".campaign37-panel" in css
    assert ".campaign37-approve" in css
    assert ".campaign37-reject" in css


def test_campaign_ui_has_no_client_side_environment_or_raw_order_mutation() -> None:
    sources = "\n".join(
        (WEB2 / filename).read_text(encoding="utf-8")
        for filename in ("campaign_operations_v36.js", "campaign_decision_v37.js")
    )
    assert "process.env" not in sources
    assert "localStorage.setItem" not in sources
    assert "/v5/order/create" not in sources
    assert "runtime flags" in sources
    assert "kill switch" in sources
