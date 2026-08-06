from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "dashboard" / "static" / "web2"


def test_portfolio_risk_use_canonical_owner() -> None:
    index = (WEB / "index.html").read_text(encoding="utf-8")
    assert "portfolio_risk_v16.css?" in index
    assert "canonical_pages_v45.js?" in index
    assert "portfolio_risk_v16.js?" not in index


def test_portfolio_risk_use_real_endpoints_only() -> None:
    js = (WEB / "canonical_pages_v45.js").read_text(encoding="utf-8")
    for route in (
        "/api/exchange/account/snapshot",
        "/api/system/runtime-truth",
        "/api/autonomous-paper/events",
        "/api/ai-control-center/daily-report",
    ):
        assert route in js
    assert "/api/run" not in js
    assert "/api/virtual-account/state" not in js
    assert "Promise.allSettled" in js
    assert "Math.random" not in js
    assert "Синтетические котировки" in js
    assert "запрещены" in js
    assert "Реальные ордера" in js


def test_portfolio_and_risk_views_are_substantive() -> None:
    js = (WEB / "canonical_pages_v45.js").read_text(encoding="utf-8")
    required = (
        "Портфель",
        "Канонические позиции",
        "Центр рисков",
        "risk_engine.canonical_service",
        "Kill switch",
        "Testnet",
        "Live",
        "Real orders",
    )
    for text in required:
        assert text in js
    assert "CouncilAuthorizedPaperLoop" in js
