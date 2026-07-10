"""Authenticated Bybit execution with hard stage, risk, and market-data gates.

Sandbox orders may be sent only when testnet credentials are configured. Live orders
require independent unlock flags, a fresh WebSocket quote, recent multi-exchange
consensus, bounded slippage, small notional limits, and a kill switch.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import uuid
from dataclasses import dataclass, asdict
from typing import Any

import httpx

from .live_execution_guard import LiveExecutionGuard


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
    client_order_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BybitExecutionClient:
    """Send market orders only after all configured safety gates pass."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.mode = os.getenv("EXCHANGE_MODE", "sandbox").strip().lower()
        self.base_url = os.getenv(
            "EXCHANGE_BASE_URL",
            "https://api-testnet.bybit.com" if self.mode == "sandbox" else "https://api.bybit.com",
        ).rstrip("/")
        self.api_key = os.getenv("EXCHANGE_API_KEY", "").strip()
        self.api_secret = os.getenv("EXCHANGE_API_SECRET", "").strip()
        self.recv_window = str(max(int(os.getenv("EXECUTION_RECV_WINDOW_MS", "2500")), 1000))
        self.max_notional = max(float(os.getenv("EXECUTION_MAX_NOTIONAL_USDT", "25")), 1.0)
        self.timeout_seconds = max(float(os.getenv("EXECUTION_HTTP_TIMEOUT_SECONDS", "3")), 1.0)
        self._client = client
        self._live_guard = LiveExecutionGuard()

    def status(self) -> dict[str, Any]:
        credentials = bool(self.api_key and self.api_secret)
        return {
            "mode": self.mode,
            "credentials_configured": credentials,
            "testnet_execution_enabled": self.mode == "sandbox" and credentials and _truthy("TESTNET_EXECUTION_ENABLED"),
            "live_execution_enabled": self._live_unlocked(credentials),
            "kill_switch": _truthy("EXECUTION_KILL_SWITCH"),
            "max_notional_usdt": self.max_notional,
            "live_market_guard_required": True,
            "recv_window_ms": int(self.recv_window),
            "http_timeout_seconds": self.timeout_seconds,
        }

    def place_market_order(self, *, symbol: str, side: str, quantity: float, reference_price: float,
                           client_order_id: str | None = None) -> ExecutionResult:
        symbol = _symbol(symbol)
        side = side.strip().title()
        if side not in {"Buy", "Sell"}:
            raise ValueError("side must be BUY or SELL")
        quantity = _positive(quantity, "quantity")
        reference_price = _positive(reference_price, "reference_price")
        notional = quantity * reference_price
        if notional > self.max_notional:
            raise RuntimeError(f"Order notional {notional:.2f} exceeds safety cap {self.max_notional:.2f} USDT")
        if _truthy("EXECUTION_KILL_SWITCH"):
            raise RuntimeError("Execution kill switch is active")
        if not self.api_key or not self.api_secret:
            raise RuntimeError("Exchange credentials are not configured")
        if self.mode == "sandbox":
            if not _truthy("TESTNET_EXECUTION_ENABLED"):
                raise RuntimeError("Testnet execution is locked")
        elif self.mode == "live":
            if not self._live_unlocked(True):
                raise RuntimeError("Live execution is locked by safety gates")
            assessment = self._live_guard.assess(symbol=symbol, reference_price=reference_price)
            if not assessment.allowed:
                raise RuntimeError("Live market guard blocked order: " + "; ".join(assessment.blockers))
        else:
            raise RuntimeError("Exchange mode does not permit execution")

        order_link_id = _client_order_id(client_order_id)
        body = {
            "category": "spot",
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
        client = self._client or httpx.Client(timeout=self.timeout_seconds)
        close_client = self._client is None
        try:
            response = client.post(f"{self.base_url}/v5/order/create", content=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
        finally:
            if close_client:
                client.close()
        code = int(data.get("retCode", -1))
        if code != 0:
            raise RuntimeError(f"Bybit rejected order: {data.get('retMsg', 'unknown error')} ({code})")
        order_id = str(data.get("result", {}).get("orderId") or "") or None
        return ExecutionResult("accepted", self.mode, symbol, side.upper(), quantity, order_id,
                               "Order accepted by Bybit", code, order_link_id)

    def _live_unlocked(self, credentials: bool) -> bool:
        return all((
            self.mode == "live",
            credentials,
            _truthy("EXCHANGE_LIVE_TRADING_ENABLED"),
            _truthy("LIVE_EXECUTION_MANUAL_UNLOCK"),
            os.getenv("LIVE_EXECUTION_CONFIRMATION", "") == "I_ACCEPT_REAL_FINANCIAL_RISK",
            not _truthy("EXECUTION_KILL_SWITCH"),
        ))


def _truthy(name: str) -> bool:
    return os.getenv(name, "0").strip().lower() in {"1", "true", "yes", "on"}


def _positive(value: Any, name: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return parsed


def _symbol(value: str) -> str:
    clean = str(value).strip().upper().replace("/", "").replace("-", "")
    if not clean.isalnum() or not clean:
        raise ValueError("invalid symbol")
    return clean


def _client_order_id(value: str | None) -> str:
    candidate = (value or f"sharipov-{uuid.uuid4().hex[:20]}").strip()
    if not candidate or len(candidate) > 36 or not all(ch.isalnum() or ch in "-_" for ch in candidate):
        raise ValueError("client_order_id must be 1-36 characters: letters, numbers, '-' or '_'")
    return candidate


def _format_number(value: float) -> str:
    return format(value, ".12f").rstrip("0").rstrip(".")
