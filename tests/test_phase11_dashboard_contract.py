from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_phase11_dashboard_assets_are_wired():
    index = (ROOT / "dashboard/static/web2/index.html").read_text(encoding="utf-8")
    init = (ROOT / "dashboard/__init__.py").read_text(encoding="utf-8")
    assert "data-phase11-production" in index
    assert "phase11_production_v43.css" in index
    assert "phase11_production_v43.js" in index
    assert "install_phase11_production_api" in init


def test_phase11_dashboard_is_mobile_and_accessibility_aware():
    css = (ROOT / "dashboard/static/web2/phase11_production_v43.css").read_text(encoding="utf-8")
    js = (ROOT / "dashboard/static/web2/phase11_production_v43.js").read_text(encoding="utf-8")
    assert "@media(max-width:560px)" in css
    assert "prefers-reduced-motion" in css
    assert "visibilitychange" in js
    assert "localStorage" in js
    assert "setInterval(load,5000)" in js


def test_phase11_deployment_is_fail_closed():
    preflight = (ROOT / "deploy/vps/phase11_release_preflight.sh").read_text(encoding="utf-8")
    verify = (ROOT / "deploy/vps/phase11_post_deploy_verify.sh").read_text(encoding="utf-8")
    assert "set -Eeuo pipefail" in preflight
    assert "EXCHANGE_LIVE_TRADING_ENABLED" in preflight
    assert "EXECUTION_KILL_SWITCH" in preflight
    assert "PRAGMA quick_check" in verify
    assert "mv -f" in verify
