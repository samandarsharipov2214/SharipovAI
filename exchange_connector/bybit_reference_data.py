"""Read-only Bybit fee and instrument reference data for guarded Testnet use.

The client has no order create/amend/cancel methods. It fetches the account-specific
fee tier and public instrument filters, validates them, and persists a bounded
snapshot in the canonical ProjectDatabase. Consumers must fail closed when the
snapshot is unavailable or stale.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import time
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from typing import Any, Mapping
from urllib.parse import urlencode

import httpx

from storage import ProjectDatabase

from .bybit_credentials import execution_credentials
from .bybit_hosts import validate_bybit_base_url
from .bybit_retry import request_with_safe_get_retries

_NAMESPACE = "bybit_trading_reference"
_ALLOWED_CATEGORIES = {"spot", "linear", "inverse", "option"}


@dataclass(frozen=True, slots=True)
class FeeSchedule:
    category: str
    symbol: str
    maker_fee_rate: float
    taker_fee_rate: float
    source: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class InstrumentRules:
    category: str
    symbol: str
    status: str
    base_coin: str
    quote_coin: str
    tick_size: float
    quantity_step: float
    minimum_quantity: float
    minimum_notional: float
    maximum_market_quantity: float
    funding_interval_minutes: int
    source: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def normalize_quantity(
        self,
        *,
        requested_quantity: float,
        reference_price: float,
        maximum_notional: float,
    ) -> float:
        quantity = _positive_decimal(requested_quantity, "requested_quantity")
        price = _positive_decimal(reference_price, "reference_price")
        cap = _positive_decimal(maximum_notional, "maximum_notional")
        step = _positive_decimal(self.quantity_step, "quantity_step")
        maximum_market = _positive_decimal(
            self.maximum_market_quantity,
            "maximum_market_quantity",
        )
        capped = min(quantity, cap / price, maximum_market)
        normalized = (capped / step).to_integral_value(rounding=ROUND_DOWN) * step
        if normalized <= 0:
            raise ValueError("quantity becomes zero after qtyStep normalization")
        if normalized < _positive_decimal(self.minimum_quantity, "minimum_quantity"):
            raise ValueError("normalized quantity is below Bybit minimum quantity")
        notional = normalized * price
        if notional < _positive_decimal(self.minimum_notional, "minimum_notional"):
            raise ValueError("normalized order is below Bybit minimum notional")
        if notional > cap:
            raise RuntimeError("normalized order exceeds shadow notional cap")
        return float(normalized)


@dataclass(frozen=True, slots=True)
class TradingReferenceSnapshot:
    environment: str
    category: str
    symbol: str
    received_at_ms: int
    expires_at_ms: int
    fee: FeeSchedule
    instrument: InstrumentRules

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["fee"] = self.fee.to_dict()
        payload["instrument"] = self.instrument.to_dict()
        return payload

    @property
    def fresh(self) -> bool:
        return int(time.time() * 1000) <= self.expires_at_ms


class BybitTradingReferenceClient:
    """Fetch and cache current Bybit fee tier and instrument filters."""

    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        database: ProjectDatabase | None = None,
        environment: str | None = None,
        ttl_seconds: float | None = None,
    ) -> None:
        raw_environment = str(environment or os.getenv("EXCHANGE_MODE", "sandbox")).strip().lower()
        if raw_environment in {"sandbox", "testnet"}:
            self.environment = "sandbox"
        elif raw_environment in {"live", "mainnet"}:
            # Reference reads may be used for offline diagnostics, never execution.
            self.environment = "live"
        else:
            raise ValueError("Bybit reference environment must be sandbox or live")
        default_url = (
            "https://api-testnet.bybit.com"
            if self.environment == "sandbox"
            else "https://api.bybit.com"
        )
        configured_url = os.getenv("EXCHANGE_BASE_URL", default_url).strip() or default_url
        self.base_url = validate_bybit_base_url(configured_url, environment=self.environment)
        credentials = execution_credentials(self.environment)
        self.api_key = credentials.api_key
        self.api_secret = credentials.api_secret
        self.credential_profile = credentials.profile
        self.recv_window = os.getenv("BYBIT_RECV_WINDOW", "5000").strip() or "5000"
        self.timeout = _bounded_float("BYBIT_REFERENCE_TIMEOUT_SECONDS", 10.0, 1.0, 30.0)
        configured_ttl = ttl_seconds if ttl_seconds is not None else _bounded_float(
            "BYBIT_REFERENCE_TTL_SECONDS",
            300.0,
            30.0,
            900.0,
        )
        self.ttl_ms = int(min(max(float(configured_ttl), 30.0), 900.0) * 1000)
        self._client = client
        self.database = database or ProjectDatabase()
        self.database.initialize()

    def status(self) -> dict[str, Any]:
        return {
            "provider": "bybit",
            "environment": self.environment,
            "base_url": self.base_url,
            "credential_profile": self.credential_profile,
            "credentials_configured": bool(self.api_key and self.api_secret),
            "read_only": True,
            "ttl_ms": self.ttl_ms,
        }

    def get(
        self,
        symbol: str,
        *,
        category: str = "spot",
        allow_network: bool = True,
        now_ms: int | None = None,
    ) -> TradingReferenceSnapshot:
        clean_symbol = _symbol(symbol)
        clean_category = _category(category)
        now = int(time.time() * 1000) if now_ms is None else _positive_int(now_ms, "now_ms")
        cached = self._load(clean_symbol, clean_category)
        if cached is not None and cached.expires_at_ms >= now:
            return cached
        if not allow_network:
            raise RuntimeError("Bybit trading reference snapshot is missing or stale")
        return self.refresh(clean_symbol, category=clean_category, now_ms=now)

    def refresh(
        self,
        symbol: str,
        *,
        category: str = "spot",
        now_ms: int | None = None,
    ) -> TradingReferenceSnapshot:
        clean_symbol = _symbol(symbol)
        clean_category = _category(category)
        now = int(time.time() * 1000) if now_ms is None else _positive_int(now_ms, "now_ms")
        instrument_payload = self._public_get(
            "/v5/market/instruments-info",
            {"category": clean_category, "symbol": clean_symbol},
        )
        fee_payload = self._private_get(
            "/v5/account/fee-rate",
            {"category": clean_category, "symbol": clean_symbol},
        )
        snapshot = TradingReferenceSnapshot(
            environment=self.environment,
            category=clean_category,
            symbol=clean_symbol,
            received_at_ms=now,
            expires_at_ms=now + self.ttl_ms,
            fee=_normalize_fee(fee_payload, category=clean_category, symbol=clean_symbol),
            instrument=_normalize_instrument(
                instrument_payload,
                category=clean_category,
                symbol=clean_symbol,
            ),
        )
        current = self.database.get_json(_NAMESPACE, self._key(clean_symbol, clean_category))
        version = int(current["version"]) if current else 0
        self.database.put_json(
            _NAMESPACE,
            self._key(clean_symbol, clean_category),
            snapshot.to_dict(),
            expected_version=version,
        )
        return snapshot

    def _load(self, symbol: str, category: str) -> TradingReferenceSnapshot | None:
        current = self.database.get_json(_NAMESPACE, self._key(symbol, category))
        if current is None:
            return None
        payload = current.get("value")
        if not isinstance(payload, Mapping):
            raise RuntimeError("Bybit trading reference cache is malformed")
        return _snapshot(payload)

    def _key(self, symbol: str, category: str) -> str:
        return f"{self.environment}:{category}:{symbol}"

    def _public_get(self, path: str, params: Mapping[str, Any]) -> dict[str, Any]:
        query = urlencode(sorted((key, value) for key, value in params.items() if value is not None))
        client = self._client or httpx.Client(timeout=self.timeout)
        close_client = self._client is None

        def perform_get() -> httpx.Response:
            return client.get(f"{self.base_url}{path}?{query}")

        try:
            response = request_with_safe_get_retries(perform_get)
            response.raise_for_status()
            data = response.json()
        finally:
            if close_client:
                client.close()
        return _accepted_payload(data)

    def _private_get(self, path: str, params: Mapping[str, Any]) -> dict[str, Any]:
        if not self.api_key or not self.api_secret:
            raise RuntimeError("Bybit credentials are required to fetch the actual fee tier")
        query = urlencode(sorted((key, value) for key, value in params.items() if value is not None))
        client = self._client or httpx.Client(timeout=self.timeout)
        close_client = self._client is None

        def perform_get() -> httpx.Response:
            timestamp = str(int(time.time() * 1000))
            payload = f"{timestamp}{self.api_key}{self.recv_window}{query}"
            signature = hmac.new(
                self.api_secret.encode("utf-8"),
                payload.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            return client.get(
                f"{self.base_url}{path}?{query}",
                headers={
                    "X-BAPI-API-KEY": self.api_key,
                    "X-BAPI-TIMESTAMP": timestamp,
                    "X-BAPI-RECV-WINDOW": self.recv_window,
                    "X-BAPI-SIGN": signature,
                },
            )

        try:
            response = request_with_safe_get_retries(perform_get)
            response.raise_for_status()
            data = response.json()
        finally:
            if close_client:
                client.close()
        return _accepted_payload(data)


def _normalize_fee(payload: Mapping[str, Any], *, category: str, symbol: str) -> FeeSchedule:
    rows = payload.get("result", {}).get("list", []) if isinstance(payload.get("result"), Mapping) else []
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("Bybit fee response contains no rows")
    row = next((item for item in rows if str(item.get("symbol") or symbol).upper() == symbol), rows[0])
    maker = _rate(row.get("makerFeeRate"), "makerFeeRate")
    taker = _rate(row.get("takerFeeRate"), "takerFeeRate")
    return FeeSchedule(category, symbol, maker, taker, "bybit_v5_account_fee_rate")


def _normalize_instrument(
    payload: Mapping[str, Any],
    *,
    category: str,
    symbol: str,
) -> InstrumentRules:
    result = payload.get("result")
    rows = result.get("list", []) if isinstance(result, Mapping) else []
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("Bybit instrument response contains no rows")
    row = next((item for item in rows if str(item.get("symbol", "")).upper() == symbol), None)
    if not isinstance(row, Mapping):
        raise RuntimeError(f"Bybit instrument {symbol} was not returned")
    status = str(row.get("status") or "")
    if status != "Trading":
        raise RuntimeError(f"Bybit instrument {symbol} is not Trading")
    lot = row.get("lotSizeFilter") if isinstance(row.get("lotSizeFilter"), Mapping) else {}
    price = row.get("priceFilter") if isinstance(row.get("priceFilter"), Mapping) else {}
    quantity_step = lot.get("qtyStep") or lot.get("basePrecision")
    minimum_notional = lot.get("minNotionalValue") or lot.get("minOrderAmt")
    maximum_market = lot.get("maxMktOrderQty") or lot.get("maxMarketOrderQty")
    minimum_quantity = lot.get("minOrderQty") or quantity_step
    return InstrumentRules(
        category=category,
        symbol=symbol,
        status=status,
        base_coin=str(row.get("baseCoin") or "").upper(),
        quote_coin=str(row.get("quoteCoin") or "").upper(),
        tick_size=float(_positive_decimal(price.get("tickSize"), "tickSize")),
        quantity_step=float(_positive_decimal(quantity_step, "quantity_step")),
        minimum_quantity=float(_positive_decimal(minimum_quantity, "minimum_quantity")),
        minimum_notional=float(_positive_decimal(minimum_notional, "minimum_notional")),
        maximum_market_quantity=float(
            _positive_decimal(maximum_market, "maximum_market_quantity")
        ),
        funding_interval_minutes=max(0, int(row.get("fundingInterval") or 0)),
        source="bybit_v5_market_instruments_info",
    )


def _snapshot(payload: Mapping[str, Any]) -> TradingReferenceSnapshot:
    fee = payload.get("fee")
    instrument = payload.get("instrument")
    if not isinstance(fee, Mapping) or not isinstance(instrument, Mapping):
        raise RuntimeError("Bybit trading reference cache is incomplete")
    return TradingReferenceSnapshot(
        environment=str(payload.get("environment") or ""),
        category=_category(payload.get("category")),
        symbol=_symbol(payload.get("symbol")),
        received_at_ms=_positive_int(payload.get("received_at_ms"), "received_at_ms"),
        expires_at_ms=_positive_int(payload.get("expires_at_ms"), "expires_at_ms"),
        fee=FeeSchedule(
            category=_category(fee.get("category")),
            symbol=_symbol(fee.get("symbol")),
            maker_fee_rate=_rate(fee.get("maker_fee_rate"), "maker_fee_rate"),
            taker_fee_rate=_rate(fee.get("taker_fee_rate"), "taker_fee_rate"),
            source=str(fee.get("source") or "cache"),
        ),
        instrument=InstrumentRules(
            category=_category(instrument.get("category")),
            symbol=_symbol(instrument.get("symbol")),
            status=str(instrument.get("status") or ""),
            base_coin=str(instrument.get("base_coin") or ""),
            quote_coin=str(instrument.get("quote_coin") or ""),
            tick_size=float(_positive_decimal(instrument.get("tick_size"), "tick_size")),
            quantity_step=float(
                _positive_decimal(instrument.get("quantity_step"), "quantity_step")
            ),
            minimum_quantity=float(
                _positive_decimal(instrument.get("minimum_quantity"), "minimum_quantity")
            ),
            minimum_notional=float(
                _positive_decimal(instrument.get("minimum_notional"), "minimum_notional")
            ),
            maximum_market_quantity=float(
                _positive_decimal(
                    instrument.get("maximum_market_quantity"),
                    "maximum_market_quantity",
                )
            ),
            funding_interval_minutes=max(
                0,
                int(instrument.get("funding_interval_minutes") or 0),
            ),
            source=str(instrument.get("source") or "cache"),
        ),
    )


def _accepted_payload(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise RuntimeError("Bybit response must be an object")
    code = int(data.get("retCode", -1))
    if code != 0:
        raise RuntimeError(
            f"Bybit rejected reference request: {data.get('retMsg', 'unknown error')} ({code})"
        )
    return data


def _category(value: Any) -> str:
    clean = str(value or "").strip().lower()
    if clean not in _ALLOWED_CATEGORIES:
        raise ValueError("category must be spot, linear, inverse or option")
    return clean


def _symbol(value: Any) -> str:
    clean = str(value or "").strip().upper().replace("/", "").replace("-", "")
    if not clean or not clean.isalnum():
        raise ValueError("invalid Bybit symbol")
    return clean


def _positive_decimal(value: Any, name: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise ValueError(f"{name} must be positive and finite")
    return parsed


def _rate(value: Any, name: str) -> float:
    parsed = float(_positive_decimal(value, name))
    if parsed > 0.05:
        raise ValueError(f"{name} is outside the permitted range")
    return parsed


def _positive_int(value: Any, name: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _bounded_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    if not math.isfinite(parsed):
        return default
    return min(max(parsed, minimum), maximum)


__all__ = [
    "BybitTradingReferenceClient",
    "FeeSchedule",
    "InstrumentRules",
    "TradingReferenceSnapshot",
]
