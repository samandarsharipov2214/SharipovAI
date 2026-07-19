from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_index_installs_phase10_and_phase11_assets_without_removing_existing_campaign_ui():
    index = (ROOT / "dashboard/static/web2/index.html").read_text(encoding="utf-8")
    for token in (
        "campaign_operations_v36.js",
        "campaign_monitor_v38.js",
        "campaign_analysis_v40.js",
        "campaign_scaling_v41.js",
        "data-phase10-scaling-performance",
        "data-phase11-production",
        "phase10_scaling_performance_v42.js",
        "phase11_production_v43.js",
        "phase10_scaling_performance_v42.css",
        "phase11_production_v43.css",
        "theme-color",
        "viewport",
    ):
        assert token in index


def test_phase11_ui_is_accessible_mobile_and_reduced_motion_aware():
    script = (ROOT / "dashboard/static/web2/phase11_production_v43.js").read_text(encoding="utf-8")
    stylesheet = (ROOT / "dashboard/static/web2/phase11_production_v43.css").read_text(encoding="utf-8")
    for token in (
        "aria-live",
        "AbortController",
        "visibilitychange",
        "localStorage",
        "lastSuccessfulAt",
        "replaceChildren",
        "navigator.onLine",
    ):
        assert token in script
    for token in (
        "prefers-reduced-motion",
        "prefers-color-scheme",
        ":focus-visible",
        "@media(max-width:560px)",
        "min-height:44px",
    ):
        assert token in stylesheet
    assert "innerHTML" not in script
    assert "eval(" not in script


def test_phase10_and_phase11_routes_are_early_admin_guarded():
    guard = (ROOT / "dashboard/admin_guard.py").read_text(encoding="utf-8")
    for prefix in (
        "/api/campaigns/phase10/",
        "/api/performance/phase10/",
        "/api/risk/phase10/",
        "/api/production/phase11/",
    ):
        assert prefix in guard
    phase10 = (ROOT / "dashboard/phase10_scaling_api.py").read_text(encoding="utf-8")
    phase11 = (ROOT / "dashboard/phase11_production_api.py").read_text(encoding="utf-8")
    assert "allow_inf_nan" in phase10
    assert "extra\": \"forbid" in phase10
    assert "_AuditCache" in phase11
    assert "active_activations" in phase11
    assert "mainnet_enabled\": False" in phase11
