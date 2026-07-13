from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI

from dashboard.currency_api import UsdRubRateService, install_currency_api, parse_cbr_usd_rub
from dashboard.evidence_vault_api import install_evidence_vault_api
from dashboard.learning_os_api import install_learning_os_api
from dashboard.source_status_compat_api import install_source_status_compat_api


ROOT = Path(__file__).resolve().parents[1]
WEB2 = ROOT / "dashboard" / "static" / "web2"
CBR_XML = b'''<?xml version="1.0" encoding="windows-1251"?>
<ValCurs Date="13.07.2026" name="Foreign Currency Market">
  <Valute ID="R01235">
    <NumCode>840</NumCode><CharCode>USD</CharCode><Nominal>1</Nominal>
    <Name>US Dollar</Name><Value>81,2500</Value><VunitRate>81,2500</VunitRate>
  </Valute>
</ValCurs>'''


def _endpoint(app: FastAPI, path: str) -> Callable[..., dict[str, Any]]:
    for route in app.routes:
        if getattr(route, "path", "") == path:
            return route.endpoint
    raise AssertionError(f"route missing: {path}")


def test_learning_and_evidence_status_routes_return_persistent_empty_safe_contracts(tmp_path, monkeypatch):
    monkeypatch.setenv("LEARNING_MEMORY_DB", str(tmp_path / "learning.sqlite3"))
    monkeypatch.setenv("EVIDENCE_VAULT_DB", str(tmp_path / "evidence.sqlite3"))

    app = FastAPI()
    install_learning_os_api(app)
    install_evidence_vault_api(app)
    install_source_status_compat_api(app)

    learning = _endpoint(app, "/api/learning-os/status")()
    evidence = _endpoint(app, "/api/evidence-vault/recent")()

    assert learning["status"] == "ok"
    assert learning["source"] == "learning_memory"
    assert isinstance(learning["items"], list)
    assert isinstance(learning["summary"], dict)

    assert evidence["status"] == "ok"
    assert evidence["source"] == "evidence_vault"
    assert isinstance(evidence["items"], list)
    assert isinstance(evidence["summary"], dict)


def test_currency_api_parses_cbr_rate_and_keeps_cached_fallback(tmp_path):
    rate, date = parse_cbr_usd_rub(CBR_XML)
    assert rate == 81.25
    assert date == "13.07.2026"

    cache = tmp_path / "usd_rub.json"
    service = UsdRubRateService(cache_path=cache, fetcher=lambda: CBR_XML, ttl_seconds=60)
    fresh = service.get_rate(force=True)
    assert fresh["status"] == "ok"
    assert fresh["rub_per_usdt_estimate"] == 81.25
    assert fresh["stale"] is False

    def offline_fetcher() -> bytes:
        raise RuntimeError("offline")

    fallback = UsdRubRateService(cache_path=cache, fetcher=offline_fetcher, ttl_seconds=60).get_rate(force=True)
    assert fallback["rub_per_usd"] == 81.25
    assert fallback["stale"] is True


def test_currency_route_installs_once():
    app = FastAPI()
    install_currency_api(app)
    install_currency_api(app)
    paths = [getattr(route, "path", "") for route in app.routes]
    assert paths.count("/api/currency/usd-rub") == 1


def test_web2_counts_core_services_and_marks_private_bybit_optional():
    core = (WEB2 / "web2.js").read_text(encoding="utf-8")
    system = (WEB2 / "system_status_v11.js").read_text(encoding="utf-8")
    overview = (WEB2 / "overview_runtime_v25.js").read_text(encoding="utf-8")

    assert "/api/learning-os/status" in core
    assert "/api/evidence-vault/recent" in core
    assert "/api/market/bybit-websocket/status" in core
    assert "/api/exchange/account/status" in core
    assert "required: false" in core
    assert "основных API" in core
    assert "Часть источников недоступна (" not in core

    assert "/api/exchange/account/status" in system
    assert "НЕ НАСТРОЕН" in system
    assert "Не влияет на виртуальную торговлю" in system
    assert "Автоматическая проверка каждые 15 секунд" in system
    assert "Записей:" not in system
    assert "Состояние:" not in system

    assert "/api/currency/usd-rub" in overview
    assert "Рубли ₽" in overview
    assert "sharipovai-display-currency" in overview
