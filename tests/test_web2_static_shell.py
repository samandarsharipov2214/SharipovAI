from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB2 = ROOT / "dashboard" / "static" / "web2"
INDEX = WEB2 / "index.html"
SCRIPT = WEB2 / "web2.js"
STYLE = WEB2 / "web2.css"
TRUTH_GUARD = WEB2 / "truth_guard.js"
HOST = ROOT / "dashboard" / "web2_host.py"


def test_web2_files_exist_and_are_nonempty() -> None:
    for path in (INDEX, SCRIPT, STYLE, TRUTH_GUARD):
        assert path.is_file(), path
        assert path.stat().st_size > 500, path


def test_all_required_navigation_sections_are_present() -> None:
    html = INDEX.read_text(encoding="utf-8")
    required = {
        "overview": "Обзор",
        "market": "Рынок",
        "decision": "Решение ИИ",
        "portfolio": "Портфель",
        "trades": "Сделки",
        "bots": "Центр ИИ",
        "chat": "ИИ-чат",
        "news": "Новости",
        "risk": "Центр рисков",
        "bybit": "Bybit",
        "learning": "Центр обучения",
        "control": "Главное управление",
        "evidence": "Хранилище доказательств",
        "virtual": "Виртуальный счёт",
        "campaigns": "Кампании",
        "reports": "Отчёты",
        "settings": "Настройки",
    }
    for page, label in required.items():
        assert f'data-page="{page}"' in html
        assert label in html


def test_brand_spelling_and_no_old_name() -> None:
    combined = "\n".join(path.read_text(encoding="utf-8") for path in (INDEX, SCRIPT))
    assert "SharipovAI" in combined
    assert "SHARIPOVAI" in combined
    assert "SharipoAI" not in combined
    assert "SHARIPOAI" not in combined


def test_ui_has_resilient_truthful_fallback_content() -> None:
    html = INDEX.read_text(encoding="utf-8")
    script = SCRIPT.read_text(encoding="utf-8")
    truth = TRUTH_GUARD.read_text(encoding="utf-8")
    assert "Интерфейс не подменяет отсутствующие значения" in html
    assert "Promise.allSettled" in script
    assert "SYNTHETIC_PHRASES" in truth
    assert "НЕТ ПОДТВЕРЖДЁННОГО СОБЫТИЯ" in truth
    assert "Evidence Vault" in truth
    assert "sanitizeBotCards" in truth
    assert "Math.random" not in script


def test_single_service_asset_paths_and_no_cache_host() -> None:
    html = INDEX.read_text(encoding="utf-8")
    host = HOST.read_text(encoding="utf-8")
    assert "/static/web2/web2.css?" in html
    assert "/static/web2/web2.js?" in html
    assert "/static/web2/logo.svg?" in html
    assert "/static/web2/truth_guard.js?" in html
    assert "no-store, no-cache, must-revalidate" in host
