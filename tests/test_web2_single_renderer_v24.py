from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "dashboard" / "static" / "web2"


def test_new_core_is_loaded_and_old_broad_renderers_are_not_loaded():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert "web2_core_v24.js" in html
    assert "overview_decision_v24.js" in html
    assert "incident_center_v24.js" in html
    assert '/static/web2/web2.js' not in html
    assert '/static/web2/sections_v10.js' not in html


def test_all_pages_have_one_explicit_owner():
    source = (WEB / "navigation_coordinator_v23.js").read_text(encoding="utf-8")
    pairs = re.findall(r"\['([^']+)',\s*'([^']+)'\]", source)
    pages = [page for page, _ in pairs]
    owners = dict(pairs)
    required = {"overview", "market", "decision", "portfolio", "trades", "bots", "chat", "news", "risk", "bybit", "learning", "control", "evidence", "virtual", "reports", "settings", "system-status", "operations", "incidents"}
    assert required <= set(pages)
    assert len(pages) == len(set(pages))
    assert owners["overview"] == "overview_decision_v24.js"
    assert owners["chat"] == "web2_core_v24.js"
    assert owners["incidents"] == "incident_center_v24.js"


def test_coordinator_uses_explicit_render_permission():
    source = (WEB / "navigation_coordinator_v23.js").read_text(encoding="utf-8")
    assert "new Error().stack" not in source
    assert "canRender" in source


def test_new_renderers_do_not_generate_random_data():
    for name in ("web2_core_v24.js", "overview_decision_v24.js", "incident_center_v24.js"):
        source = (WEB / name).read_text(encoding="utf-8")
        assert "Math.random(" not in source
        assert "mockData" not in source
        assert "fakeData" not in source
