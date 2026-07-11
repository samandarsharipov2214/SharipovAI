"""Verified public Bybit instrument rules with bounded caching.

The service fetches `/v5/market/instruments-info`, validates the returned trading
symbol and normalizes exchange constraints for the non-executing preview layer.
No credentials or order endpoints are used.
"""
from __future__ import annotations

import os
import time
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx


class InstrumentRulesUnavailable(RuntimeError):
    """Raised when current exchange rules cannot be verified safely."""


@dataclass(frozen=True, slots=True)
class BybitInstrumentRules:
    symbol: str
    category: str
    status: str
    tick_size: Decimal
    qty_step: Decimal
    min_qty: Decimal
    min_notional: Decimal
    max_limit_qty: Decimal | None
    max_market_qty: Decimal | None
    min_leverage: Decimal | None
    max_leverage: Decimal | None
    fetched_at_ms: int
    source: str = "bybit_v5_instruments_info"

    def to_dict(self) -> dict[str, Any]:
        raw = asdict(self)
        for key, value in list(raw.items()):
            if isinstance(value, Decimal):
                raw[key] = str(value)
        return raw

    def preview_fields(self) -> dict[str, str]:
        return {
            "tick_size": str(self.tick_size),
            "qty_step": str(self.qty_step),
            "min_qty": str(self.min_qty),
            "min_notional": str(self.min_notional),
        }


class BybitInstrumentRulesService:
    """Fetch and cache current public trading constraints from Bybit."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.base_url = os.getenv("BYBIT_PUBLIC_BASE_URL", "https://api.bybit.com").rstrip("/")
        self.timeout = max(float(os.getenv("BYBIT_INSTRUMENT_TIMEOUT_SECONDS", "5")), 0.5)
        self.ttl_seconds = min(max(float(os.getenv("BYBIT_INSTRUMENT_CACHE_TTL_SECONDS", "300")), 5.0), 3600.0)
        self._client = client
        self._cache: dict[tuple[str, str], tuple[float, BybitInstrumentRules]] = {}

    def get(self, symbol: str, category: str = "spot") -> BybitInstrumentRules:
        clean_symbol = _symbol(symbol)
        clean_category = str(category).strip().lower()
        if clean_category not in {"spot", "linear", "inverse"}:
            raise ValueError("category must be spot, linear or inverse")
        key = (clean_category, clean_symbol)
        cached = self._cache.get(key)
        now_mono = time.monotonic()
        if cached and now_mono - cached[0] <= self.ttl_seconds:
            return cached[1]

        response = self._get(
            f"{self.base_url}/v5/market/instruments-info",
            params={"category": clean_category, "symbol": clean_symbol},
        )
        payload = response.json()
        if int(payload.get("retCode", -1)) != 0:
            raise InstrumentRulesUnavailable(
                f"Bybit rejected instruments-info: {payload.get('retMsg', 'unknown error')}"
            )
        rows = payload.get("result", {}).get("list", []) or []
        if len(rows) != 1:
            raise InstrumentRulesUnavailable(
                f"expected exactly one instrument for {clean_symbol}, received {len(rows)}"
            )
        rules = _parse_rules(rows[0], clean_symbol, clean_category)
        self._cache[key] = (now_mono, rules)
        return rules

    def invalidate(self, symbol: str | None = None, category: str | None = None) -> None:
        if symbol is None and category is None:
            self._cache.clear()
            return
        clean_symbol = _symbol(symbol) if symbol is not None else None
        clean_category = category.strip().lower() if category else None
        for key in list(self._cache):
            if (clean_symbol is None or key[1] == clean_symbol) and (
                clean_category is None or key[0] == clean_category
            ):
                self._cache.pop(key, None)

    def _get(self, url: str, *, params: dict[str, str]) -> httpx.Response:
        try:
            if self._client is not None:
                response = self._client.get(url, params=params, timeout=self.timeout)
            else:
                response = httpx.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            return response
        except httpx.HTTPError as exc:
            raise InstrumentRulesUnavailable(f"unable to fetch Bybit instrument rules: {exc}") from exc


def _parse_rules(row: dict[str, Any], symbol: str, category: str) -> BybitInstrumentRules:
    if str(row.get("symbol", "")).upper() != symbol:
        raise InstrumentRulesUnavailable("Bybit returned rules for a different symbol")
    status = str(row.get("status", ""))
    if status != "Trading":
        raise InstrumentRulesUnavailable(f"instrument is not tradable: status={status or 'unknown'}")

    price_filter = row.get("priceFilter") or {}
    lot = row.get("lotSizeFilter") or {}
    tick_size = _positive_decimal(price_filter.get("tickSize"), "tickSize")

    if category == "spot":
        qty_step = _positive_decimal(lot.get("basePrecision"), "basePrecision")
        min_qty = _nonnegative_decimal(lot.get("minOrderQty", "0"), "minOrderQty")
        min_notional = _positive_decimal(lot.get("minOrderAmt"), "minOrderAmt")
        max_limit_qty = _optional_positive(lot.get("maxLimitOrderQty"))
        max_market_qty = _optional_positive(lot.get("maxMarketOrderQty"))
        min_leverage = max_leverage = None
    else:
        qty_step = _positive_decimal(lot.get("qtyStep"), "qtyStep")
        min_qty = _positive_decimal(lot.get("minOrderQty"), "minOrderQty")
        min_notional = _positive_decimal(lot.get("minNotionalValue"), "minNotionalValue")
        max_limit_qty = _optional_positive(lot.get("maxOrderQty"))
        max_market_qty = _optional_positive(lot.get("maxMktOrderQty"))
        leverage = row.get("leverageFilter") or {}
        min_leverage = _optional_positive(leverage.get("minLeverage"))
        max_leverage = _optional_positive(leverage.get("maxLeverage"))

    return BybitInstrumentRules(
        symbol=symbol,
        category=category,
        status=status,
        tick_size=tick_size,
        qty_step=qty_step,
        min_qty=min_qty,
        min_notional=min_notional,
        max_limit_qty=max_limit_qty,
        max_market_qty=max_market_qty,
        min_leverage=min_leverage,
        max_leverage=max_leverage,
        fetched_at_ms=int(time.time() * 1000),
    )


def _symbol(value: Any) -> str:
    clean = str(value or "").strip().upper().replace("/", "").replace("-", "")
    if not clean or not clean.isalnum() or len(clean) > 30:
        raise ValueError("symbol is invalid")
    return clean


def _positive_decimal(value: Any, name: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise InstrumentRulesUnavailable(f"{name} is invalid") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise InstrumentRulesUnavailable(f"{name} must be positive")
    return parsed


def _nonnegative_decimal(value: Any, name: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise InstrumentRulesUnavailable(f"{name} is invalid") from exc
    if not parsed.is_finite() or parsed < 0:
        raise InstrumentRulesUnavailable(f"{name} must be nonnegative")
    return parsed


def _optional_positive(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    return _positive_decimal(value, "optional limit")
