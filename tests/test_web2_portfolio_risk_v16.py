from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "dashboard" / "static" / "web2"


def test_portfolio_risk_assets_connected():
    index = (WEB / "index.html").read_text(encoding="utf-8")
    assert "portfolio_risk_v16.css" in index
    assert "portfolio_risk_v16.js" in index


def test_portfolio_risk_uses_real_endpoints_only():
    js = (WEB / "portfolio_risk_v16.js").read_text(encoding="utf-8")
    for route in (
        "/api/exchange/account/snapshot",
        "/api/run",
        "/api/virtual-account/state",
        "/api/ai-control-center/daily-report",
    ):
        assert route in js
    assert "Math.random" not in js
    assert "Синтетические значения','запрещены" in js


def test_portfolio_and_risk_views_are_substantive():
    js = (WEB / "portfolio_risk_v16.js").read_text(encoding="utf-8")
    required = (
        "Распределение капитала",
        "Нереализованный PnL",
        "Рыночная экспозиция",
        "Макс. концентрация",
        "Максимальный риск сделки",
        "Максимальная просадка",
        "Лимит дневного убытка",
        "Торговля",
        "Предупреждения",
    )
    for text in required:
        assert text in js
