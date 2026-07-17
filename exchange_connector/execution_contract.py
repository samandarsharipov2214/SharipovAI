"""Canonical execution envelope for exchange-bound SharipovAI requests.

A :class:`TradingCandidate` is analytical evidence.  An
:class:`ApprovedExecutionRequest` is the only object an exchange execution
adapter may submit.  Mainnet execution is deliberately compiled out while the
project remains in paper/testnet validation.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from typing import Any

from trading_candidate import (
    CandidateValidation,
    TradingCandidate,
    TradingCategory,
    TradingDecision,
    TradingEnvironment,
    TradingSide,
)

from .bybit_order_identity import OrderIntent

MAINNET_EXECUTION_COMPILED = False
_MAX_REQUEST_LIFETIME_MS = 10_000
_ORDER_LINK_PATTERN = re.compile(r"^sai_[0-9a-f]{32}$")


@dataclass(frozen=True, slots=True)
class ApprovedExecutionRequest:
    """Immutable, short-lived request accepted by an exchange adapter."""

    candidate_id: str
    candidate_hash: str
    symbol: str
    category: TradingCategory
    side: TradingSide
    environment: TradingEnvironment
    quantity: float
    reference_price: float
    order_link_id: str
    created_at_ms: int
    expires_at_ms: int
    portfolio_snapshot_id: str
    cost_snapshot_id: str
    security_approval_id: str = ""
    attempt: int = 1

    @property
    def notional(self) -> float:
        return float(self.quantity) * float(self.reference_price)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["category"] = self.category.value
        payload["side"] = self.side.value
        payload["environment"] = self.environment.value
        payload["notional"] = self.notional
        return payload

    def to_order_intent(self) -> OrderIntent:
        """Return the deterministic idempotency intent for this request."""

        return OrderIntent.create(
            candidate_id=self.candidate_id,
            environment=self.environment.value,
            category=self.category.value,
            symbol=self.symbol,
            side=self.side.value,
            order_type="Market",
            quantity=self.quantity,
            price=None,
            time_in_force="IOC",
            reduce_only=False,
            position_idx=0,
            market_unit="baseCoin",
            attempt=self.attempt,
        )


def build_execution_request(
    candidate: TradingCandidate,
    validation: CandidateValidation,
    *,
    quantity: float,
    now_ms: int,
    attempt: int = 1,
) -> ApprovedExecutionRequest:
    """Create a canonical testnet execution request from validated evidence."""

    if not isinstance(candidate, TradingCandidate):
        raise TypeError("candidate must be TradingCandidate")
    if not isinstance(validation, CandidateValidation):
        raise TypeError("validation must be CandidateValidation")
    if not validation.valid or validation.decision is not TradingDecision.ALLOW:
        raise RuntimeError("candidate validation does not permit execution")
    if candidate.decision is not TradingDecision.ALLOW:
        raise RuntimeError("candidate decision is not ALLOW")
    if candidate.environment is TradingEnvironment.PAPER:
        raise RuntimeError("paper candidates must use virtual execution")
    if candidate.environment is TradingEnvironment.MAINNET:
        raise RuntimeError("mainnet execution is compiled out")
    if candidate.environment is not TradingEnvironment.TESTNET:
        raise RuntimeError("unsupported execution environment")

    clean_now = _positive_int(now_ms, "now_ms")
    clean_quantity = _positive_float(quantity, "quantity")
    clean_attempt = _positive_int(attempt, "attempt")
    if candidate.expires_at_ms <= clean_now:
        raise RuntimeError("candidate expired before execution request creation")

    candidate_hash = _candidate_hash(candidate)
    provisional = ApprovedExecutionRequest(
        candidate_id=candidate.candidate_id,
        candidate_hash=candidate_hash,
        symbol=candidate.symbol,
        category=candidate.category,
        side=candidate.side,
        environment=candidate.environment,
        quantity=clean_quantity,
        reference_price=_positive_float(candidate.reference_price, "reference_price"),
        order_link_id="",
        created_at_ms=clean_now,
        expires_at_ms=min(candidate.expires_at_ms, clean_now + _MAX_REQUEST_LIFETIME_MS),
        portfolio_snapshot_id=candidate.portfolio_snapshot_id,
        cost_snapshot_id=candidate.cost_snapshot_id,
        security_approval_id=candidate.security_approval_id,
        attempt=clean_attempt,
    )
    order_link_id = provisional.to_order_intent().order_link_id()
    request = ApprovedExecutionRequest(**{**asdict(provisional), "order_link_id": order_link_id})
    validate_execution_request(request, now_ms=clean_now)
    return request


def validate_execution_request(request: ApprovedExecutionRequest, *, now_ms: int) -> None:
    """Fail closed when an exchange request is incomplete, stale or unsafe."""

    if not isinstance(request, ApprovedExecutionRequest):
        raise TypeError("request must be ApprovedExecutionRequest")
    clean_now = _positive_int(now_ms, "now_ms")
    for name, value in (
        ("candidate_id", request.candidate_id),
        ("portfolio_snapshot_id", request.portfolio_snapshot_id),
        ("cost_snapshot_id", request.cost_snapshot_id),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} is required")
    if request.environment is TradingEnvironment.MAINNET:
        raise RuntimeError("mainnet execution is compiled out")
    if request.environment is not TradingEnvironment.TESTNET:
        raise RuntimeError("exchange execution currently permits testnet only")
    if request.category is not TradingCategory.SPOT:
        raise RuntimeError("only spot testnet execution is currently permitted")
    if not request.symbol or request.symbol != request.symbol.upper() or not request.symbol.isalnum():
        raise ValueError("symbol must be uppercase alphanumeric")
    _positive_float(request.quantity, "quantity")
    _positive_float(request.reference_price, "reference_price")
    _positive_int(request.attempt, "attempt")
    if not math.isfinite(request.notional) or request.notional <= 0:
        raise ValueError("notional must be positive and finite")
    if request.created_at_ms <= 0 or request.created_at_ms > clean_now + 1_000:
        raise ValueError("created_at_ms is invalid")
    if request.expires_at_ms <= clean_now:
        raise RuntimeError("execution request is expired")
    if request.expires_at_ms - request.created_at_ms > _MAX_REQUEST_LIFETIME_MS:
        raise ValueError("execution request lifetime exceeds hard limit")
    if not _ORDER_LINK_PATTERN.fullmatch(request.order_link_id):
        raise ValueError("order_link_id must be a canonical sai_ SHA-256 identity")
    if len(request.candidate_hash) != 64 or any(ch not in "0123456789abcdef" for ch in request.candidate_hash):
        raise ValueError("candidate_hash must be a SHA-256 hex digest")
    intent = request.to_order_intent()
    if intent.order_link_id() != request.order_link_id:
        raise ValueError("order_link_id does not match execution intent")


def _candidate_hash(candidate: TradingCandidate) -> str:
    payload = json.dumps(candidate.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _positive_float(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a positive finite number")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError(f"{name} must be a positive finite number")
    return parsed


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a positive integer")
    parsed = int(value)
    if parsed <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return parsed


__all__ = [
    "ApprovedExecutionRequest",
    "MAINNET_EXECUTION_COMPILED",
    "build_execution_request",
    "validate_execution_request",
]
