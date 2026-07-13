"""Verified USD/RUB reference rate for readable virtual-account display."""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI
from fastapi.responses import JSONResponse

CBR_DAILY_URL = "https://www.cbr.ru/scripts/XML_daily.asp"
DEFAULT_CACHE_PATH = Path("/var/lib/sharipovai/usd_rub_rate.json")
CACHE_TTL_SECONDS = 6 * 60 * 60
FetchBytes = Callable[[], bytes]


class UsdRubRateService:
    """Fetch the official daily USD/RUB rate and retain a durable fallback."""

    def __init__(
        self,
        *,
        cache_path: str | Path | None = None,
        fetcher: FetchBytes | None = None,
        ttl_seconds: int = CACHE_TTL_SECONDS,
    ) -> None:
        configured = cache_path or os.getenv("SHARIPOVAI_USD_RUB_CACHE_PATH") or DEFAULT_CACHE_PATH
        self.cache_path = Path(configured)
        self.fetcher = fetcher or _fetch_cbr_daily_xml
        self.ttl_seconds = max(60, int(ttl_seconds))
        self._lock = threading.RLock()

    def get_rate(self, *, force: bool = False) -> dict[str, Any]:
        with self._lock:
            cached = self._read_cache()
            if not force and cached and _cache_age_seconds(cached) <= self.ttl_seconds:
                return _public_payload(cached, stale=False)

            try:
                rate, effective_date = parse_cbr_usd_rub(self.fetcher())
                record = {
                    "rub_per_usd": rate,
                    "effective_date": effective_date,
                    "source": "Банк России",
                    "source_url": CBR_DAILY_URL,
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                }
                self._write_cache(record)
                return _public_payload(record, stale=False)
            except Exception as exc:
                if cached:
                    payload = _public_payload(cached, stale=True)
                    payload["warning_ru"] = f"Свежий курс временно не получен; используется сохранённый: {type(exc).__name__}"
                    return payload
                raise RuntimeError(f"USD/RUB rate unavailable: {type(exc).__name__}: {exc}") from exc

    def _read_cache(self) -> dict[str, Any] | None:
        try:
            value = json.loads(self.cache_path.read_text(encoding="utf-8"))
            if float(value.get("rub_per_usd", 0.0) or 0.0) <= 0:
                return None
            return value
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None

    def _write_cache(self, record: dict[str, Any]) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.cache_path.with_suffix(self.cache_path.suffix + ".tmp")
        temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.cache_path)


def parse_cbr_usd_rub(payload: bytes | str) -> tuple[float, str]:
    """Parse one Bank of Russia daily XML document."""

    raw = payload.encode("utf-8") if isinstance(payload, str) else payload
    root = ET.fromstring(raw)
    effective_date = str(root.attrib.get("Date") or "")
    for valute in root.findall("Valute"):
        if (valute.findtext("CharCode") or "").strip().upper() != "USD":
            continue
        nominal = int((valute.findtext("Nominal") or "1").strip())
        value_text = (valute.findtext("Value") or "").strip().replace(" ", "").replace(",", ".")
        value = float(value_text)
        rate = value / nominal
        if rate <= 0:
            raise ValueError("Bank of Russia returned a non-positive USD/RUB rate")
        return round(rate, 6), effective_date
    raise ValueError("USD rate is missing from Bank of Russia response")


def install_currency_api(app: FastAPI) -> None:
    if getattr(app.state, "currency_api_installed", False):
        return
    app.state.currency_api_installed = True
    service = UsdRubRateService()
    app.state.usd_rub_rate_service = service

    @app.get("/api/currency/usd-rub")
    def usd_rub_rate() -> dict[str, Any] | JSONResponse:
        try:
            return service.get_rate()
        except Exception as exc:
            return JSONResponse(
                status_code=503,
                content={
                    "status": "unavailable",
                    "pair": "USD/RUB",
                    "error": f"{type(exc).__name__}: {exc}",
                    "note_ru": "Капитал продолжает учитываться в USDT; перевод в рубли временно недоступен.",
                },
            )


def _fetch_cbr_daily_xml() -> bytes:
    request = urllib.request.Request(
        CBR_DAILY_URL,
        headers={"User-Agent": "SharipovAI/1.0 currency-display"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=8) as response:
        return response.read()


def _cache_age_seconds(record: dict[str, Any]) -> float:
    try:
        fetched = datetime.fromisoformat(str(record.get("fetched_at", "")).replace("Z", "+00:00"))
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=timezone.utc)
        return max(0.0, time.time() - fetched.timestamp())
    except (TypeError, ValueError):
        return float("inf")


def _public_payload(record: dict[str, Any], *, stale: bool) -> dict[str, Any]:
    rate = round(float(record["rub_per_usd"]), 6)
    return {
        "status": "ok",
        "pair": "USD/RUB",
        "rub_per_usd": rate,
        "rub_per_usdt_estimate": rate,
        "source": str(record.get("source") or "Банк России"),
        "source_url": str(record.get("source_url") or CBR_DAILY_URL),
        "effective_date": record.get("effective_date"),
        "fetched_at": record.get("fetched_at"),
        "stale": bool(stale),
        "conversion_kind": "indicative_usdt_to_rub_via_usd",
        "note_ru": "Сумма в рублях ориентировочная: USDT пересчитывается как 1 USDT ≈ 1 USD по официальному курсу USD/RUB.",
    }
