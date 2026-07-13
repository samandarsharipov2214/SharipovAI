"""Authenticated Bybit testnet execution with a compile-time mainnet lock."""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import time
from dataclasses import asdict, dataclass
from typing import Any

import httpx

from .bybit_credentials import execution_credentials
from .bybit_hosts import validate_bybit_base_url
from .execution_contract import (
    ApprovedExecutionRequest,
    MAINNET_EXECUTION_COMPILED,
    validate_execution_request,
)


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    status: str
    mode: str
    symbol: str
    side: str
    quantity: float
    order_id: str | None
    message: str
    raw_code: int | None = None
    candidate_id: str = ""
    order_link_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BybitExecutionClient:
    """Submit spot testnet orders after all safety gates pass.

    Mainnet execution is compiled out. Environment variables cannot override
    this restriction. New code must use :meth:`execute` with an immutable
    :class:`ApprovedExecutionRequest`.
    """

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.mode = os.getenv("EXCHANGE_MODE", "sandbox").strip().lower()
        configured_url = os.getenv(
            "EXCHANGE_BASE_URL",
            "https://api-testnet.bybit.com" if self.mode == "sandbox" else "https://api.bybit.com",
        )
        self.base_url = validate_bybit_base_url(configured_url, environment=self.mode)
        credentials = execution_credentials(self.mode)
        self.api_key = credentials.api_key
        self.api_secret = credentials.api_secret
        self.credential_profile = credentials.profile
        self.recv_window = "5000"
        self.max_notional = _bounded_positive_env("EXECUTION_MAX_NOTIONAL_USDT", default=25.0, maximum=1000.0)
        self._client = client

    def status(self) -> dict[str, Any]:
        credentials = bool(self.api_key and self.api_secret)
        return {
            "mode": self.mode,
            "credential_profile": self.credential_profile,
            "credentials_configured": credentials,
            "testnet_execution_enabled": self.mode == "sandbox" and credentials and _truthy("TESTNET_EXECUTION_ENABLED"),
            "live_execution_enabled": False,
            "mainnet_execution_compiled": MAINNET_EXECUTION_COMPILED,
            "mainnet_hard_blocked": True,
            "canonical_execution_contract": "ApprovedExecutionRequest",
            "kill_switch": _truthy("EXECUTION_KILL_SWITCH"),
            "max_notional_usdt": self.max_notional,
        }

    def execute(self, request: ApprovedExecutionRequest, *, now_ms: int | None = None) -> ExecutionResult:
        """Execute one canonical, short-lived testnet request."""

        current_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
        validate_execution_request(request, now_ms=current_ms)
        if self.mode != "sandbox":
            raise RuntimeError("Mainnet execution is compiled out; exchange mode must be sandbox")
        if request.environment.value != "testnet":
            raise RuntimeError("Canonical exchange execution currently permits testnet only")
        return self._submit_market_order(
            symbol=request.symbol,
            side=request.side.value,
            quantity=request.quantity,
            reference_price=request.reference_price,
            category=request.category.value,
            order_link_id=request.order_link_id,
            candidate_id=request.candidate_id,
        )

    def place_market_order(self, *, symbol: str, side: str, quantity: float, reference_price: float) -> ExecutionResult:
        """Deprecated testnet-only compatibility path.

        This method can never execute in live mode. It remains temporarily for
        existing testnet bridge code while callers migrate to ``execute``.
        """

        if self.mode != "sandbox":
            raise RuntimeError("Mainnet execution is compiled out")
        return self._submit_market_order(
            symbol=symbol,
            side=side,
            quantity=quantity,
            reference_price=reference_price,
            category="spot",
            order_link_id=_legacy_order_link_id(symbol, side),
            candidate_id="legacy-testnet-compatibility",
        )

    def _submit_market_order(
        self,
        *,
        symbol: str,
        side: str,
        quantity: float,
        reference_price: float,
        category: str,
        order_link_id: str,
        candidate_id: str,
    ) -> ExecutionResult:
        if self.mode != "sandbox":
            raise RuntimeError("Mainnet execution is compiled out")
        symbol = _symbol(symbol)
        side = side.strip().title()
        if side not in {"Buy", "Sell"}:
            raise ValueError("side must be BUY or SELL")
        if category != "spot":
            raise RuntimeError("Only spot testnet execution is permitted")
        quantity = _positive(quantity, "quantity")
        reference_price = _positive(reference_price, "reference_price")
        notional = quantity * reference_price
        if not math.isfinite(notional):
            raise ValueError("order notional must be finite")
        if notional > self.max_notional:
            raise RuntimeError(f"Order notional {notional:.2f} exceeds safety cap {self.max_notional:.2f} USDT")
        if _truthy("EXECUTION_KILL_SWITCH"):
            raise RuntimeError("Execution kill switch is active")
        if not self.api_key or not self.api_secret:
            raise RuntimeError(f"{self.credential_profile} credentials are not configured")
        if not _truthy("TESTNET_EXECUTION_ENABLED"):
            raise RuntimeError("Testnet execution is locked")

        base_url = validate_bybit_base_url(self.base_url, environment="sandbox")
        body = {
            "category": category,
            "symbol": symbol,
            "side": side,
            "orderType": "Market",
            "qty": _format_number(quantity),
            "marketUnit": "baseCoin",
            "orderLinkId": order_link_id,
        }
        timestamp = str(int(time.time() * 1000))
        payload = json.dumps(body, separators=(",", ":"))
        signature = hmac.new(
            self.api_secret.encode(),
            f"{timestamp}{self.api_key}{self.recv_window}{payload}".encode(),
            hashlib.sha256,
        ).hexdigest()
        headers = {
            "X-BAPI-API-KEY": self.api_key,
            "X-BAPI-TIMESTAMP": timestamp,
            "X-BAPI-RECV-WINDOW": self.recv_window,
            "X-BAPI-SIGN": signature,
            "Content-Type": "application/json",
        }
        client = self._client or httpx.Client(timeout=10.0)
        close_client = self._client is None
        try:
            response = client.post(f"{base_url}/v5/order/create", content=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
        finally:
            if close_client:
                client.close()
        code = int(data.get("retCode", -1))
        if code != 0:
            raise RuntimeError(f"Bybit rejected order: {data.get('retMsg', 'unknown error')} ({code})")
        order_id = str(data.get("result", {}).get("orderId") or "") or None
        return ExecutionResult(
            "accepted",
            self.mode,
            symbol,
            side.upper(),
            quantity,
            order_id,
            "Testnet order accepted by Bybit",
            code,
            candidate_id,
            order_link_id,
        )

    def _live_unlocked(self, credentials: bool) -> bool:
        """Backward-compatible status hook; mainnet is always hard-blocked."""

        del credentials
        return False


def _truthy(name: str) -> bool:
    return os.getenv(name, "0").strip().lower() in {"1", "true", "yes", "on"}


def _positive(value: Any, name: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError(f"{name} must be a finite number greater than zero")
    return parsed


def _bounded_positive_env(name: str, *, default: float, maximum: float) -> float:
    try:
        parsed = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    if not math.isfinite(parsed) or parsed <= 0:
        return default
    return min(parsed, maximum)


def _symbol(value: str) -> str:
    clean = str(value).strip().upper().replace("/", "").replace("-", "")
    if not clean.isalnum() or not clean:
        raise ValueError("invalid symbol")
    return clean


def _format_number(value: float) -> str:
    return format(value, ".12f").rstrip("0").rstrip(".")


def _legacy_order_link_id(symbol: str, side: str) -> str:
    seed = f"{_symbol(symbol)}:{str(side).strip().title()}:{time.time_ns()}"
    return f"SAI-L-{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:24]}"
