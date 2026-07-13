from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "dashboard" / "static" / "web2"


def test_system_status_assets_exist_and_are_loaded() -> None:
    index = (WEB / "index.html").read_text(encoding="utf-8")
    assert (WEB / "system_status_v11.js").is_file()
    assert (WEB / "system_status_v11.css").is_file()
    assert "/static/web2/system_status_v11.css?" in index
    assert "/static/web2/system_status_v11.js?" in index


def test_system_status_checks_real_project_endpoints() -> None:
    script = (WEB / "system_status_v11.js").read_text(encoding="utf-8")
    required = {
        "/api/health",
        "/api/market/bybit-websocket/status",
        "/api/exchange/account/status",
        "/api/ai-bots",
        "/api/run",
        "/api/social-news",
        "/api/learning-os/status",
        "/api/evidence-vault/recent",
        "/api/virtual-account/state",
        "/api/ai-control-center/daily-report",
    }
    for endpoint in required:
        assert endpoint in script


def test_system_status_does_not_claim_success_without_response() -> None:
    script = (WEB / "system_status_v11.js").read_text(encoding="utf-8")
    assert "Promise.allSettled" in script
    assert "НЕДОСТУПЕН" in script
    assert "Доступен» означает успешный и семантически корректный ответ API" in script
    assert "реальные ордера остаются заблокированными" in script
    assert "Math.random" not in script
