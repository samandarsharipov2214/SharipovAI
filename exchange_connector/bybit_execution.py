"""Authenticated Bybit testnet execution with hard idempotency and mainnet locks."""
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

from storage import ProjectDatabase

from .bybit_credentials import execution_credentials
from .bybit_hosts import validate_bybit_base_url
from .execution_contract import (
    ApprovedExecutionRequest,
    MAINNET_EXECUTION_COMPILED,
    validate_execution_request,
)
from .execution_idempotency import ExecutionIdempotencyRepository
from .execution_kill_switch import PersistentExecutionKillSwitch

_SUBMISSION_CAPABILITY = object()


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


class BybitRejectedOrder(RuntimeError):
    """Known exchange rejection with no accepted order."""

    def __init__(self, message: str, code: int) -> None:
        self.code = int(code)
        super().__init__(f"Bybit rejected order: {message} ({self.code})")


class BybitExecutionClient:
    """Submit only canonical ``ApprovedExecutionRequest`` objects to Testnet.

    Mainnet is compiled out. Every request is durably reserved before the
    network call. Unknown outcomes remain unresolved, trip a persistent kill
    switch and require explicit reconciliation before execution can resume.
    """

    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        database: ProjectDatabase | None = None,
        idempotency: ExecutionIdempotencyRepository | None = None,
        kill_switch: PersistentExecutionKillSwitch | None = None,
    ) -> None:
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
        self.max_notional = _bounded_positive_env(
            "EXECUTION_MAX_NOTIONAL_USDT",
            default=25.0,
            maximum=1000.0,
        )
        self._client = client
        self.database = database or ProjectDatabase()
        self.database.initialize()
        self.idempotency = idempotency or ExecutionIdempotencyRepository(
            database=self.database,
            environment="testnet",
        )
        self.kill_switch = kill_switch or PersistentExecutionKillSwitch(self.database)

    def status(self) -> dict[str, Any]:
        credentials = bool(self.api_key and self.api_secret)
        identity = self.idempotency.snapshot()
        kill_switch = self.kill_switch.state()
        unresolved_count = len(identity["unresolved"])
        return {
            "mode": self.mode,
            "credential_profile": self.credential_profile,
            "credentials_configured": credentials,
            "testnet_execution_enabled": (
                self.mode == "sandbox"
                and credentials
                and _truthy("TESTNET_EXECUTION_ENABLED")
                and not kill_switch.active
                and unresolved_count == 0
            ),
            "live_execution_enabled": False,
            "mainnet_execution_compiled": MAINNET_EXECUTION_COMPILED,
            "mainnet_hard_blocked": True,
            "canonical_execution_contract": "ApprovedExecutionRequest",
            "direct_submission_methods": 0,
            "idempotency_repository": "ProjectDatabase/OrderIntentRegistry",
            "unresolved_execution_count": unresolved_count,
            "restart_safe": bool(identity["restart_safe"]) and unresolved_count == 0,
            "kill_switch": kill_switch.active,
            "kill_switch_state": kill_switch.to_dict(),
            "max_notional_usdt": self.max_notional,
        }

    def execute(
        self,
        request: ApprovedExecutionRequest,
        *,
        now_ms: int | None = None,
    ) -> ExecutionResult:
        """Reserve, submit and bind one canonical Testnet request.

        No mapping, candidate, raw symbol/side tuple or dashboard payload is
        accepted here. A duplicate or any pre-existing unresolved reservation
        blocks before the exchange call.
        """

        if not isinstance(request, ApprovedExecutionRequest):
            raise TypeError("request must be ApprovedExecutionRequest")
        current_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
        validate_execution_request(request, now_ms=current_ms)
        self.kill_switch.assert_open()

        unresolved = self.idempotency.unresolved()
        if unresolved:
            self.kill_switch.trip(
                reason="unresolved_execution_state_before_submission",
                actor="BybitExecutionClient.execute",
                source="idempotency_preflight",
            )
            raise RuntimeError("execution blocked until unresolved reservations are reconciled")

        normalized = self._preflight(
            symbol=request.symbol,
            side=request.side.value,
            quantity=request.quantity,
            reference_price=request.reference_price,
            category=request.category.value,
        )
        self.idempotency.reserve(request, now_ms=current_ms)
        self.idempotency.mark_submitted(request, now_ms=current_ms)
        try:
            result = self._send_market_order(
                **normalized,
                order_link_id=request.order_link_id,
                candidate_id=request.candidate_id,
                capability=_SUBMISSION_CAPABILITY,
            )
        except BybitRejectedOrder:
            self.idempotency.mark_rejected(
                request,
                now_ms=max(current_ms, int(time.time() * 1000)),
            )
            raise
        except Exception as exc:
            self.kill_switch.trip(
                reason=f"ambiguous_exchange_outcome:{type(exc).__name__}",
                actor="BybitExecutionClient.execute",
                source="network_submission",
            )
            raise RuntimeError(
                "execution outcome is ambiguous; request remains Submitted, "
                "persistent kill switch is active and reconciliation is required"
            ) from exc
        if not result.order_id:
            self.kill_switch.trip(
                reason="accepted_response_missing_order_id",
                actor="BybitExecutionClient.execute",
                source="exchange_response",
            )
            raise RuntimeError(
                "exchange accepted response without orderId; kill switch active and reconciliation required"
            )
        self.idempotency.bind_accepted(
            request,
            order_id=result.order_id,
            now_ms=max(current_ms, int(time.time() * 1000)),
        )
        return result

    def place_market_order(
        self,
        *,
        symbol: str,
        side: str,
        quantity: float,
        reference_price: float,
    ) -> ExecutionResult:
        """Removed legacy entry point. Use ``execute(ApprovedExecutionRequest)``."""

        del symbol, side, quantity, reference_price
        raise RuntimeError(
            "legacy place_market_order path is removed; "
            "use execute(ApprovedExecutionRequest)"
        )

    def _preflight(
        self,
        *,
        symbol: str,
        side: str,
        quantity: float,
        reference_price: float,
        category: str,
    ) -> dict[str, Any]:
        if self.mode != "sandbox":
            raise RuntimeError("Mainnet execution is compiled out")
        clean_symbol = _symbol(symbol)
        clean_side = str(side).strip().title()
        if clean_side not in {"Buy", "Sell"}:
            raise ValueError("side must be BUY or SELL")
        if category != "spot":
            raise RuntimeError("Only spot testnet execution is permitted")
        clean_quantity = _positive(quantity, "quantity")
        clean_price = _positive(reference_price, "reference_price")
        notional = clean_quantity * clean_price
        if not math.isfinite(notional):
            raise ValueError("order notional must be finite")
        if notional > self.max_notional:
            raise RuntimeError(
                f"Order notional {notional:.2f} exceeds safety cap "
                f"{self.max_notional:.2f} USDT"
            )
        self.kill_switch.assert_open()
        if not self.api_key or not self.api_secret:
            raise RuntimeError(f"{self.credential_profile} credentials are not configured")
        if not _truthy("TESTNET_EXECUTION_ENABLED"):
            raise RuntimeError("Testnet execution is locked")
        return {
            "symbol": clean_symbol,
            "side": clean_side,
            "quantity": clean_quantity,
            "reference_price": clean_price,
            "category": category,
        }

    def _send_market_order(
        self,
        *,
        symbol: str,
        side: str,
        quantity: float,
        reference_price: float,
        category: str,
        order_link_id: str,
        candidate_id: str,
        capability: object,
    ) -> ExecutionResult:
        if capability is not _SUBMISSION_CAPABILITY:
            raise RuntimeError("direct exchange submission is forbidden")
        del reference_price
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
            response = client.post(
                f"{base_url}/v5/order/create",
                content=payload,
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()
        finally:
            if close_client:
                client.close()
        code = int(data.get("retCode", -1))
        if code != 0:
            raise BybitRejectedOrder(str(data.get("retMsg", "unknown error")), code)
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


__all__ = [
    "BybitExecutionClient",
    "BybitRejectedOrder",
    "ExecutionResult",
]
