from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "dashboard" / "static" / "web2"


def test_ai_center_assets_are_connected() -> None:
    index = (WEB / "index.html").read_text(encoding="utf-8")
    assert "/static/web2/ai_center_v14.js?" in index
    assert "/static/web2/ai_center_v14.css?" in index
    assert index.index("ai_center_v14.css") < index.index("ai_center_v14.js")


def test_ai_center_uses_real_project_apis() -> None:
    js = (WEB / "ai_center_v14.js").read_text(encoding="utf-8")
    for route in ("/api/ai-bots", "/api/evidence-vault/recent", "/api/run"):
        assert route in js
    assert "Math.random" not in js
    assert "Подтверждённое последнее действие не получено" in js


def test_ai_center_contains_required_views() -> None:
    js = (WEB / "ai_center_v14.js").read_text(encoding="utf-8")
    required = (
        "Карта ИИ",
        "Журнал работы",
        "Текущие задачи",
        "Связи и входящие данные",
        "Подтверждённые действия",
        "Открыть ИИ",
        "Подчиняется",
        "Последний сигнал",
    )
    for marker in required:
        assert marker in js


def test_ai_center_is_mobile_responsive() -> None:
    css = (WEB / "ai_center_v14.css").read_text(encoding="utf-8")
    assert "@media(max-width:720px)" in css
    assert ".ai14-modal" in css
    assert ".ai14-nodes" in css
