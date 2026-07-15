from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "dashboard" / "static" / "web2"


def test_system_status_assets_exist_and_are_loaded() -> None:
    index = (WEB / "index.html").read_text(encoding="utf-8")
    assert (WEB / "system_status_v11.js").is_file()
    assert (WEB / "system_status_v11.css").is_file()
    assert "system_status_v11.css?" in index
    assert "system_status_v11.js?" in index
    assert index.index("system_status_v11.css") < index.index("system_status_v11.js")


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
    assert "Promise.allSettled" in script
    assert "cache: 'no-store'" in script


def test_system_status_does_not_claim_success_without_response() -> None:
    script = (WEB / "system_status_v11.js").read_text(encoding="utf-8")
    assert "НЕДОСТУПЕН" in script
    assert "НЕ НАСТРОЕН" in script
    assert "Нет ответа" in script
    assert "Не влияет на виртуальную торговлю" in script
    assert "Ключ Bybit должен разрешать только чтение аккаунта" in script
    assert "available === required.length" in script
    assert "Math.random" not in script


def test_system_status_is_live_and_visibility_aware() -> None:
    script = (WEB / "system_status_v11.js").read_text(encoding="utf-8")
    assert "AUTO_REFRESH_MS = 15000" in script
    assert "setInterval(updateClock, 1000)" in script
    assert "!document.hidden" in script
    assert "Проверено ${seconds} сек назад" in script
    assert "Активность до 90 секунд" in script
