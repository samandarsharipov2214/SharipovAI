from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "dashboard" / "static" / "web2"
INDEX = WEB / "index.html"
JS = WEB / "canonical_pages_v45.js"
CSS = WEB / "general_control_v15.css"


def test_general_control_uses_canonical_owner() -> None:
    assert JS.exists()
    assert CSS.exists()
    html = INDEX.read_text(encoding="utf-8")
    assert "canonical_pages_v45.js" in html
    assert "general_control_v15.css" in html
    assert "general_control_v15.js" not in html
    assert 'data-page="control"' in html


def test_general_control_uses_verified_endpoints() -> None:
    source = JS.read_text(encoding="utf-8")
    for route in (
        "/api/system/runtime-truth",
        "/api/autonomous-paper/events",
        "/api/evidence-vault/recent",
    ):
        assert route in source
    assert "/api/run" not in source
    assert "/api/ai-bots" not in source
    assert "Math.random" not in source


def test_general_control_exposes_truth_and_safety() -> None:
    source = JS.read_text(encoding="utf-8")
    for label in (
        "Главное управление",
        "CouncilAuthorizedPaperLoop",
        "Каноническое решение",
        "Доказательства",
    ):
        assert label in source
