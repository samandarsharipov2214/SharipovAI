from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "dashboard" / "static" / "web2"


def test_v18_assets_are_connected() -> None:
    index = (WEB / "index.html").read_text(encoding="utf-8")
    assert "exchange_execution_settings_v18.js" in index
    assert "exchange_execution_settings_v18.css" in index


def test_v18_uses_real_project_endpoints() -> None:
    script = (WEB / "exchange_execution_settings_v18.js").read_text(encoding="utf-8")
    assert "/api/exchange/account/snapshot" in script
    assert "/api/virtual-account/state" in script
    assert "Math.random" not in script
    assert "demo" not in script.lower()


def test_v18_covers_required_pages() -> None:
    script = (WEB / "exchange_execution_settings_v18.js").read_text(encoding="utf-8")
    for page in ("bybit", "trades", "virtual", "settings"):
        assert page in script
    assert "RU" not in script or "Русский" in script
