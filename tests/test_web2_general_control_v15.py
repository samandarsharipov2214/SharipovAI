from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "dashboard" / "static" / "web2" / "index.html"
JS = ROOT / "dashboard" / "static" / "web2" / "general_control_v15.js"
CSS = ROOT / "dashboard" / "static" / "web2" / "general_control_v15.css"


def test_general_control_assets_exist_and_are_connected() -> None:
    assert JS.exists()
    assert CSS.exists()
    html = INDEX.read_text(encoding="utf-8")
    assert "general_control_v15.js" in html
    assert "general_control_v15.css" in html
    assert 'data-page="control"' in html


def test_general_control_uses_verified_endpoints() -> None:
    source = JS.read_text(encoding="utf-8")
    for route in ("/api/run", "/api/ai-bots", "/api/evidence-vault/recent"):
        assert route in source
    assert "Math.random" not in source
    assert "Подтверждённое объяснение не получено" in source
    assert "Отдельные голоса не переданы API" in source


def test_general_control_has_required_sections() -> None:
    source = JS.read_text(encoding="utf-8")
    for label in ("Обоснование", "Голоса ИИ", "Разногласия", "Цепочка доказательств"):
        assert label in source
