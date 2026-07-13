from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI

from dashboard.currency_api import UsdRubRateService, install_currency_api, parse_cbr_usd_rub


CBR_XML = b'''<?xml version="1.0" encoding="windows-1251"?>
<ValCurs Date="13.07.2026" name="Foreign Currency Market">
  <Valute ID="R01235">
    <NumCode>840</NumCode><CharCode>USD</CharCode><Nominal>1</Nominal>
    <Name>US Dollar</Name><Value>81,2500</Value><VunitRate>81,2500</VunitRate>
  </Valute>
</ValCurs>'''


def test_parse_cbr_usd_rub() -> None:
    rate, effective_date = parse_cbr_usd_rub(CBR_XML)
    assert rate == 81.25
    assert effective_date == "13.07.2026"


def test_service_uses_durable_cache_when_refresh_fails(tmp_path) -> None:
    cache = tmp_path / "rate.json"
    service = UsdRubRateService(cache_path=cache, fetcher=lambda: CBR_XML, ttl_seconds=60)
    fresh = service.get_rate(force=True)
    assert fresh["status"] == "ok"
    assert fresh["rub_per_usdt_estimate"] == 81.25
    assert fresh["stale"] is False

    failing = UsdRubRateService(
        cache_path=cache,
        fetcher=lambda: (_ for _ in ()).throw(RuntimeError("offline")),
        ttl_seconds=60,
    )
    cached = failing.get_rate(force=True)
    assert cached["status"] == "ok"
    assert cached["rub_per_usd"] == 81.25
    assert cached["stale"] is True
    assert "сохранённый" in cached["warning_ru"]


def test_currency_route_installs_once() -> None:
    app = FastAPI()
    install_currency_api(app)
    install_currency_api(app)
    paths = [getattr(route, "path", "") for route in app.routes]
    assert paths.count("/api/currency/usd-rub") == 1
    assert app.state.currency_api_installed is True


def test_cache_payload_has_current_timestamp_shape(tmp_path) -> None:
    service = UsdRubRateService(cache_path=tmp_path / "rate.json", fetcher=lambda: CBR_XML)
    payload = service.get_rate(force=True)
    stamp = datetime.fromisoformat(payload["fetched_at"].replace("Z", "+00:00"))
    assert stamp.tzinfo is not None
    assert stamp <= datetime.now(timezone.utc)
    assert payload["conversion_kind"] == "indicative_usdt_to_rub_via_usd"
