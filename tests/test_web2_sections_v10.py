from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "dashboard" / "static" / "web2" / "index.html"
SCRIPT = ROOT / "dashboard" / "static" / "web2" / "sections_v10.js"
STYLE = ROOT / "dashboard" / "static" / "web2" / "sections_v10.css"


def test_all_web2_assets_exist() -> None:
    assert INDEX.exists()
    assert SCRIPT.exists()
    assert STYLE.exists()


def test_all_sixteen_sections_are_present() -> None:
    html = INDEX.read_text(encoding="utf-8")
    pages = [
        "overview", "market", "decision", "portfolio", "trades", "bots", "chat", "news",
        "risk", "bybit", "learning", "control", "evidence", "virtual", "reports", "settings",
    ]
    for page in pages:
        assert html.count(f'data-page="{page}"') == 1
    assert "/static/web2/sections_v10.js?" in html
    assert "/static/web2/sections_v10.css?" in html


def test_critical_sections_have_real_data_routes() -> None:
    script = SCRIPT.read_text(encoding="utf-8")
    required_routes = [
        "/api/exchange/account/snapshot",
        "/api/ai-bots",
        "/api/social-news",
        "/api/learning-os/status",
        "/api/evidence-vault/recent",
        "/api/virtual-account/state",
        "/api/ai-control-center/daily-report",
    ]
    for route in required_routes:
        assert route in script


def test_truthful_fallbacks_are_explicit() -> None:
    script = SCRIPT.read_text(encoding="utf-8")
    required_phrases = [
        "нет измерений",
        "Подтверждённой записи",
        "Синтетические данные",
        "не подставляются искусственно",
        "Доказательство отсутствует",
    ]
    for phrase in required_phrases:
        assert phrase in script


def test_news_and_ai_sections_are_implemented() -> None:
    script = SCRIPT.read_text(encoding="utf-8")
    for function_name in [
        "newsPage", "botsPage", "controlPage", "riskPage", "learningPage",
        "evidencePage", "reportsPage", "portfolioPage",
    ]:
        assert f"function {function_name}" in script
    assert "Открыть источник" in script
    assert "Карта ИИ" in script
    assert "Журнал решений" in script
