"""Verified public Bybit instrument rules with bounded caching.

The service fetches `/v5/market/instruments-info`, validates the returned online
instrument, and normalizes current exchange constraints. It never authenticates
or calls order endpoints.
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from .bybit_preflight import validate_official_bybit_base_url
from .bybit_retry import request_with_safe_get_retries


class InstrumentRulesUnavailable(RuntimeError):
    """Raised when current exchange rules cannot be verified safely."""


@dataclass(frozen=True, slots=True)
class BybitInstrumentRules:
    symbol: str
    category: str
    status: str
    base_coin: str
    quote_coin: str
    tick_size: Decimal
    qty_step: Decimal
    min_qty: Decimal
    min_notional: Decimal
    max_limit_qty: Decimal | None
    max_market_qty: Decimal | None
    min_price: Decimal | None
    max_price: Decimal | None
    min_leverage: Decimal | None
    max_leverage: Decimal | None
    leverage_step: Decimal | None
    fetched_at_ms: int
    source: str = "bybit_v5_instruments_info"

    def to_dict(self) -> dict[str, Any]:
        raw = asdict(self)
        for key, value in list(raw.items()):
            if isinstance(value, Decimal):
                raw[key] = str(value)
        return raw

    def preview_fields(self, order_type: str) -> dict[str, str | None]:
        clean_type = str(order_type).strip().lower()
        if clean_type not in {"market", "limit"}:
            raise ValueError("order_type must be market or limit")
        maximum = self.max_market_qty if clean_type == "market" else self.max_limit_qty
        return {
            "tick_size": str(self.tick_size),
            "qty_step": str(self.qty_step),
            "min_qty": str(self.min_qty),
            "min_notional": str(self.min_notional),
            "max_qty": None if maximum is None else str(maximum),
            "min_price": None if self.min_price is None else str(self.min_price),
            "max_price": None if self.max_price is None else str(self.max_price),
            "min_leverage": None if self.min_leverage is None else str(self.min_leverage),
            "max_leverage": None if self.max_leverage is None else str(self.max_leverage),
        }


class BybitInstrumentRulesService:
    """Fetch and cache current public trading constraints from Bybit."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.base_url = validate_official_bybit_base_url(
            os.getenv("BYBIT_PUBLIC_BASE_URL", "https://api.bybit.com")
        )
        self.timeout = min(
            max(float(os.getenv("BYBIT_INSTRUMENT_TIMEOUT_SECONDS", "5")), 0.5),
            15.0,
        )
        self.ttl_seconds = min(
            max(float(os.getenv("BYBIT_INSTRUMENT_CACHE_TTL_SECONDS", "300")), 5.0),
            900.0,
        )
        self._client = client
        self._cache: dict[tuple[str, str], tuple[float, BybitInstrumentRules]] = {}
        self._lock = threading.RLock()

    def get(self, symbol: str, category: str = "spot") -> BybitInstrumentRules:
        clean_symbol = _symbol(symbol)
        clean_category = str(category).strip().lower()
        if clean_category not in {"spot", "linear", "inverse"}:
            raise ValueError("category must be spot, linear or inverse")
        key = (clean_category, clean_symbol)
        now_mono = time.monotonic()
        with self._lock:
            cached = self._cache.get(key)
        if cached and now_mono - cached[0] <= self.ttl_seconds:
            return cached[1]

        client = self._client or httpx.Client(timeout=self.timeout)
        close_client = self._client is None

        def perform_get() -> httpx.Response:
            return client.get(
                f"{self.base_url}/v5/market/instruments-info",
                params={"category": clean_category, "symbol": clean_symbol},
                timeout=self.timeout,
            )

        try:
            response = request_with_safe_get_retries(perform_get)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise InstrumentRulesUnavailable(
                f"unable to fetch Bybit instrument rules: {type(exc).__name__}: {exc}"
            ) from exc
        finally:
            if close_client:
                client.close()

        if not isinstance(payload, dict) or int(payload.get("retCode", -1)) != 0:
            message = payload.get("retMsg", "unknown error") if isinstance(payload, dict) else "invalid response"
            raise InstrumentRulesUnavailable(f"Bybit rejected instruments-info: {message}")
        result = payload.get("result") or {}
        if str(result.get("category", clean_category)).lower() != clean_category:
            raise InstrumentRulesUnavailable("Bybit returned a different instrument category")
        rows = result.get("list", []) or []
        if len(rows) != 1 or not isinstance(rows[0], dict):
            raise InstrumentRulesUnavailable(
                f"expected exactly one instrument for {clean_symbol}, received {len(rows)}"
            )
        rules = _parse_rules(rows[0], clean_symbol, clean_category)
        with self._lock:
            self._cache[key] = (now_mono, rules)
        return rules

    def invalidate(self, symbol: str | None = None, category: str | None = None) -> None:
        if symbol is None and category is None:
            with self._lock:
                self._cache.clear()
            return
        clean_symbol = _symbol(symbol) if symbol is not None else None
        clean_category = category.strip().lower() if category else None
        with self._lock:
            for key in list(self._cache):
                if (clean_symbol is None or key[1] == clean_symbol) and (
                    clean_category is None or key[0] == clean_category
                ):
                    self._cache.pop(key, None)


def _parse_rules(row: dict[str, Any], symbol: str, category: str) -> BybitInstrumentRules:
    if str(row.get("symbol", "")).upper() != symbol:
        raise InstrumentRulesUnavailable("Bybit returned rules for a different symbol")
    status = str(row.get("status", ""))
    if status != "Trading":
        raise InstrumentRulesUnavailable(f"instrument is not tradable: status={status or 'unknown'}")

    base_coin = _coin(row.get("baseCoin"), "baseCoin")
    quote_coin = _coin(row.get("quoteCoin"), "quoteCoin")
    price_filter = row.get("priceFilter") or {}
    lot = row.get("lotSizeFilter") or {}
    if not isinstance(price_filter, dict) or not isinstance(lot, dict):
        raise InstrumentRulesUnavailable("instrument filters have invalid structure")

    tick_size = _positive_decimal(price_filter.get("tickSize"), "tickSize")
    min_price = _optional_positive(price_filter.get("minPrice"))
    max_price = _optional_positive(price_filter.get("maxPrice"))

    if category == "spot":
        qty_step = _positive_decimal(lot.get("basePrecision"), "basePrecision")
        # Bybit marks spot minOrderQty as deprecated. The technical minimum
        # quantity is one basePrecision step; minimum value is enforced by minOrderAmt.
        min_qty = qty_step
        min_notional = _positive_decimal(lot.get("minOrderAmt"), "minOrderAmt")
        max_limit_qty = _optional_positive(lot.get("maxLimitOrderQty"))
        max_market_qty = _optional_positive(lot.get("maxMarketOrderQty"))
        min_leverage = max_leverage = leverage_step = None
    else:
        qty_step = _positive_decimal(lot.get("qtyStep"), "qtyStep")
        min_qty = _positive_decimal(lot.get("minOrderQty"), "minOrderQty")
        min_notional = _positive_decimal(lot.get("minNotionalValue"), "minNotionalValue")
        max_limit_qty = _optional_positive(lot.get("maxOrderQty"))
        max_market_qty = _optional_positive(lot.get("maxMktOrderQty"))
        leverage = row.get("leverageFilter") or {}
        if not isinstance(leverage, dict):
            raise InstrumentRulesUnavailable("leverageFilter has invalid structure")
        min_leverage = _positive_decimal(leverage.get("minLeverage"), "minLeverage")
        max_leverage = _positive_decimal(leverage.get("maxLeverage"), "maxLeverage")
        leverage_step = _positive_decimal(leverage.get("leverageStep"), "leverageStep")
        if min_leverage > max_leverage:
            raise InstrumentRulesUnavailable("minimum leverage exceeds maximum leverage")

    for maximum in (max_limit_qty, max_market_qty):
        if maximum is not None and maximum < min_qty:
            raise InstrumentRulesUnavailable("maximum quantity is below minimum quantity")
    if min_price is not None and max_price is not None and min_price > max_price:
        raise InstrumentRulesUnavailable("minimum price exceeds maximum price")

    return BybitInstrumentRules(
        symbol=symbol,
        category=category,
        status=status,
        base_coin=base_coin,
        quote_coin=quote_coin,
        tick_size=tick_size,
        qty_step=qty_step,
        min_qty=min_qty,
        min_notional=min_notional,
        max_limit_qty=max_limit_qty,
        max_market_qty=max_market_qty,
        min_price=min_price,
        max_price=max_price,
        min_leverage=min_leverage,
        max_leverage=max_leverage,
        leverage_step=leverage_step,
        fetched_at_ms=int(time.time() * 1000),
    )


def _symbol(value: Any) -> str:
    clean = str(value or "").strip().upper().replace("/", "").replace("-", "")
    if not clean or not clean.isalnum() or len(clean) > 30:
        raise ValueError("symbol is invalid")
    return clean


def _coin(value: Any, name: str) -> str:
    clean = str(value or "").strip().upper()
    if not clean or not clean.isalnum() or len(clean) > 20:
        raise InstrumentRulesUnavailable(f"{name} is invalid")
    return clean


def _positive_decimal(value: Any, name: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise InstrumentRulesUnavailable(f"{name} is invalid") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise InstrumentRulesUnavailable(f"{name} must be positive")
    return parsed


def _optional_positive(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    return _positive_decimal(value, "optional limit")
