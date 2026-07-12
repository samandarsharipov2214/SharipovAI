from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "dashboard" / "static" / "web2" / "index.html"
SCRIPT = ROOT / "dashboard" / "static" / "web2" / "web2.js"
STYLE = ROOT / "dashboard" / "static" / "web2" / "web2.css"


def test_web2_files_exist_and_are_nonempty() -> None:
    for path in (INDEX, SCRIPT, STYLE):
        assert path.is_file(), path
        assert path.stat().st_size > 500, path


def test_all_required_navigation_sections_are_present() -> None:
    html = INDEX.read_text(encoding="utf-8")
    required_ids = [
        "overview", "market", "decision", "portfolio", "trades", "bots",
        "chat", "news", "risk", "bybit", "learning", "control",
        "evidence", "virtual", "reports", "settings",
    ]
    for page_id in required_ids:
        assert f'data-page="{page_id}"' in html
    for label in ("Обзор", "Рынок", "Решение ИИ", "Портфель", "Сделки", "Новости", "Настройки"):
        assert label in html


def test_brand_spelling_and_no_old_name() -> None:
    combined = "\n".join(path.read_text(encoding="utf-8") for path in (INDEX, SCRIPT))
    assert "SharipovAI" in combined
    assert "SHARIPOVAI" in combined
    assert "SharipoAI" not in combined
    assert "SHARIPOAI" not in combined


def test_ui_has_resilient_fallback_content() -> None:
    html = INDEX.read_text(encoding="utf-8")
    script = SCRIPT.read_text(encoding="utf-8")
    assert "Данные появятся после ответа API" in html
    assert "Promise.allSettled" in script
    assert "Выдуманные сделки не отображаются" in script
    assert "не подставляет выдуманные цены" in script


def test_single_service_asset_paths() -> None:
    html = INDEX.read_text(encoding="utf-8")
    assert '/static/web2/web2.css?v=8' in html
    assert '/static/web2/web2.js?v=8' in html
    assert '/static/web2/logo.svg?v=6' in html
