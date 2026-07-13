import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB2 = ROOT / "dashboard" / "static" / "web2"
INDEX = WEB2 / "index.html"
SCRIPT = WEB2 / "web2.js"
STYLE = WEB2 / "web2.css"


def _all_javascript() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted(WEB2.glob("*.js")))


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
    combined = INDEX.read_text(encoding="utf-8") + "\n" + _all_javascript()
    assert "SharipovAI" in combined
    assert "SHARIPOVAI" in combined
    assert "SharipoAI" not in combined
    assert "SHARIPOAI" not in combined


def test_ui_has_resilient_fallback_content() -> None:
    html = INDEX.read_text(encoding="utf-8")
    scripts = _all_javascript()
    assert "Данные появятся после ответа API" in html
    assert "Promise.allSettled" in scripts
    assert any(
        marker in scripts
        for marker in (
            "без выдуманных показателей",
            "без выдуманных участников",
            "без демонстрационных операций",
        )
    )
    assert "Реальные свечи и котировки с Bybit" in scripts


def test_single_service_asset_paths() -> None:
    html = INDEX.read_text(encoding="utf-8")
    css = re.search(r'href="/static/web2/web2\.css\?v=(\d+)"', html)
    js = re.search(r'src="/static/web2/web2\.js\?v=(\d+)"', html)
    assert css is not None
    assert js is not None
    assert css.group(1) == js.group(1)

    references = re.findall(r'(?:href|src)="(/static/web2/[^\"]+)"', html)
    assert references
    for reference in references:
        relative = reference.split("?", 1)[0].removeprefix("/static/web2/")
        assert (WEB2 / relative).is_file(), reference
