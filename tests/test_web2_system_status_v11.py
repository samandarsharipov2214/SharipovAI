from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "dashboard" / "static" / "web2"


def test_system_status_assets_exist_and_are_loaded() -> None:
    index = (WEB / "index.html").read_text(encoding="utf-8")
    assert (WEB / "system_status_v44.js").is_file()
    assert (WEB / "system_status_v11.css").is_file()
    assert "system_status_v11.css?" in index
    assert "system_status_v44.js?" in index
    assert index.index("system_status_v11.css") < index.index("system_status_v44.js")
    assert "system_status_v11.js" not in index


def test_system_status_checks_canonical_and_supporting_sources() -> None:
    script = (WEB / "system_status_v44.js").read_text(encoding="utf-8")
    required = {
        "/api/system/runtime-truth",
        "/api/market/stream/status",
        "/api/exchange/account/status",
        "/api/social-news",
        "/api/learning-os/status",
        "/api/evidence-vault/recent",
        "/api/ai-control-center/daily-report",
    }
    for endpoint in required:
        assert endpoint in script
    assert "/api/run" not in script
    assert "/api/ai-bots" not in script
    assert "/api/virtual-account/state" not in script
    assert "Promise.allSettled" in script
    assert "cache:'no-store'" in script


def test_system_status_separates_transport_from_semantic_health() -> None:
    script = (WEB / "system_status_v44.js").read_text(encoding="utf-8")
    assert "Доступность транспорта отделена от реального состояния runtime" in script
    assert "не вычисляется из количества HTTP 200" in script
    assert "НЕТ ОТВЕТА" in script
    assert "НЕ НАСТРОЕН" in script
    assert "не влияет на canonical paper runtime" in script
    assert "truth.status" in script
    assert "Math.random" not in script


def test_system_status_is_live_and_visibility_aware() -> None:
    script = (WEB / "system_status_v44.js").read_text(encoding="utf-8")
    assert "setInterval(()=>{if(active()&&!document.hidden)load()" in script
    assert "},15000)" in script
    assert "setInterval(()=>{const clock" in script
    assert "Проверено ${seconds} сек назад" in script
    assert "CouncilAuthorizedPaperLoop" in script
    assert "real_orders_blocked" in script
