from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "dashboard" / "static" / "web2"


def test_canonical_execution_pages_are_connected() -> None:
    index = (WEB / "index.html").read_text(encoding="utf-8")
    assert "canonical_pages_v45.js" in index
    assert "exchange_execution_settings_v18.css" in index
    assert "exchange_execution_settings_v18.js" not in index


def test_canonical_execution_pages_use_real_read_only_sources() -> None:
    script = (WEB / "canonical_pages_v45.js").read_text(encoding="utf-8")
    for route in (
        "/api/system/runtime-truth",
        "/api/autonomous-paper/events",
        "/api/exchange/account/snapshot",
    ):
        assert route in script
    assert "/api/virtual-account/state" not in script
    assert "/api/run" not in script
    assert "Math.random" not in script


def test_canonical_execution_owner_covers_required_pages() -> None:
    script = (WEB / "canonical_pages_v45.js").read_text(encoding="utf-8")
    for page in ("bybit", "trades", "virtual", "settings"):
        assert f"'{page}'" in script
    assert "CouncilAuthorizedPaperLoop" in script
    assert "Реальный ордер: нет" in script
