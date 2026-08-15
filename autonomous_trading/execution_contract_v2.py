"""Canonical, non-executing execution contract for Architecture V2.

This module defines the transport-neutral order intent that future paper,
testnet and mainnet adapters must consume. It deliberately contains no exchange
I/O and grants no execution authority. Paper remains authoritative until a
separate reviewed migration explicitly promotes another environment.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from hashlib import sha256
import json
import re
from typing import Protocol, runtime_checkable

from autonomous_trading.general_controller_v2 import TradingIntent


_SYMBOL_RE = re.compile(r"^[A-Z0-9]{3,32}$")


class ExecutionEnvironment(StrEnum):
    PAPER = "paper"
    TESTNET = "testnet"
    MAINNET = "mainnet"


class OrderType(StrEnum):
    MARKET = "market"
    LIMIT = "limit"


class TimeInForce(StrEnum):
    GTC = "GTC"
    IOC = "IOC"
    FOK = "FOK"


def _decimal(value: Decimal | str | int | float, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be a decimal value") from exc
    if not result.is_finite():
        raise ValueError(f"{field} must be finite")
    return result


def _positive(value: Decimal | str | int | float, field: str) -> Decimal:
    result = _decimal(value, field)
    if result <= 0:
        raise ValueError(f"{field} must be positive")
    return result


def _non_negative(value: Decimal | str | int | float, field: str) -> Decimal:
    result = _decimal(value, field)
    if result < 0:
        raise ValueError(f"{field} must be non-negative")
    return result


def _is_step_aligned(value: Decimal, step: Decimal) -> bool:
    return value % step == 0


@dataclass(frozen=True, slots=True)
class InstrumentConstraints:
    """Fresh exchange limits captured before order preparation."""

    tick_size: Decimal
    qty_step: Decimal
    min_qty: Decimal
    min_notional: Decimal
    evidence_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "tick_size", _positive(self.tick_size, "tick_size"))
        object.__setattr__(self, "qty_step", _positive(self.qty_step, "qty_step"))
        object.__setattr__(self, "min_qty", _positive(self.min_qty, "min_qty"))
        object.__setattr__(self, "min_notional", _positive(self.min_notional, "min_notional"))
        if not self.evidence_id.strip():
            raise ValueError("constraints evidence_id must not be empty")


@dataclass(frozen=True, slots=True)
class PreTradeCostSnapshot:
    """Immutable fee/slippage estimate linked to evidence."""

    fee_rate: Decimal
    expected_slippage_rate: Decimal
    worst_case_slippage_rate: Decimal
    evidence_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "fee_rate", _non_negative(self.fee_rate, "fee_rate"))
        object.__setattr__(
            self,
            "expected_slippage_rate",
            _non_negative(self.expected_slippage_rate, "expected_slippage_rate"),
        )
        object.__setattr__(
            self,
            "worst_case_slippage_rate",
            _non_negative(self.worst_case_slippage_rate, "worst_case_slippage_rate"),
        )
        if self.worst_case_slippage_rate < self.expected_slippage_rate:
            raise ValueError("worst_case_slippage_rate must be >= expected_slippage_rate")
        if not self.evidence_id.strip():
            raise ValueError("cost evidence_id must not be empty")


@dataclass(frozen=True, slots=True)
class CanonicalExecutionIntent:
    """One deterministic intent shared by paper and future real adapters.

    The contract can describe testnet/mainnet targets so migration can be tested,
    but it can never authorize a write. An adapter may only consume this record
    after separate runtime safety gates that live outside this module.
    """

    candidate_id: str
    symbol: str
    category: str
    intent: TradingIntent
    environment: ExecutionEnvironment
    quantity: Decimal
    reference_price: Decimal
    order_type: OrderType
    time_in_force: TimeInForce
    constraints: InstrumentConstraints
    costs: PreTradeCostSnapshot
    portfolio_snapshot_id: str
    risk_evidence_id: str
    security_evidence_id: str
    decision_evidence_id: str
    expires_at_ms: int
    limit_price: Decimal | None = None
    reduce_only: bool = False
    paper_authoritative: bool = True
    execution_authority: bool = False

    def __post_init__(self) -> None:
        candidate_id = self.candidate_id.strip()
        symbol = self.symbol.strip().upper()
        category = self.category.strip().lower()
        if not candidate_id:
            raise ValueError("candidate_id must not be empty")
        if not _SYMBOL_RE.fullmatch(symbol):
            raise ValueError("symbol must be 3..32 uppercase alphanumeric characters")
        if category not in {"spot", "linear"}:
            raise ValueError("category must be spot or linear")
        if self.intent is TradingIntent.WAIT:
            raise ValueError("WAIT cannot produce an execution intent")
        if self.expires_at_ms <= 0:
            raise ValueError("expires_at_ms must be positive")
        if not self.paper_authoritative:
            raise ValueError("paper_authoritative must remain true in this migration phase")
        if self.execution_authority:
            raise ValueError("execution_authority must remain false in this migration phase")

        quantity = _positive(self.quantity, "quantity")
        reference_price = _positive(self.reference_price, "reference_price")
        limit_price = None if self.limit_price is None else _positive(self.limit_price, "limit_price")
        if self.order_type is OrderType.LIMIT and limit_price is None:
            raise ValueError("limit orders require limit_price")
        if self.order_type is OrderType.MARKET and limit_price is not None:
            raise ValueError("market orders must not define limit_price")
        if not _is_step_aligned(quantity, self.constraints.qty_step):
            raise ValueError("quantity is not aligned to qty_step")
        if quantity < self.constraints.min_qty:
            raise ValueError("quantity is below min_qty")
        price_for_notional = limit_price if limit_price is not None else reference_price
        if limit_price is not None and not _is_step_aligned(limit_price, self.constraints.tick_size):
            raise ValueError("limit_price is not aligned to tick_size")
        if quantity * price_for_notional < self.constraints.min_notional:
            raise ValueError("order notional is below min_notional")

        for field_name in (
            "portfolio_snapshot_id",
            "risk_evidence_id",
            "security_evidence_id",
            "decision_evidence_id",
        ):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} must not be empty")

        object.__setattr__(self, "candidate_id", candidate_id)
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "category", category)
        object.__setattr__(self, "quantity", quantity)
        object.__setattr__(self, "reference_price", reference_price)
        object.__setattr__(self, "limit_price", limit_price)

    @property
    def idempotency_key(self) -> str:
        """Deterministic key for duplicate/restart protection."""

        payload = self._stable_payload()
        digest = sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return f"v2-{digest[:32]}"

    @property
    def order_link_id(self) -> str:
        """Exchange-friendly deterministic identifier derived from the intent."""

        return self.idempotency_key

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["intent"] = self.intent.value
        payload["environment"] = self.environment.value
        payload["order_type"] = self.order_type.value
        payload["time_in_force"] = self.time_in_force.value
        payload["quantity"] = str(self.quantity)
        payload["reference_price"] = str(self.reference_price)
        payload["limit_price"] = None if self.limit_price is None else str(self.limit_price)
        payload["constraints"] = {
            "tick_size": str(self.constraints.tick_size),
            "qty_step": str(self.constraints.qty_step),
            "min_qty": str(self.constraints.min_qty),
            "min_notional": str(self.constraints.min_notional),
            "evidence_id": self.constraints.evidence_id,
        }
        payload["costs"] = {
            "fee_rate": str(self.costs.fee_rate),
            "expected_slippage_rate": str(self.costs.expected_slippage_rate),
            "worst_case_slippage_rate": str(self.costs.worst_case_slippage_rate),
            "evidence_id": self.costs.evidence_id,
        }
        payload["idempotency_key"] = self.idempotency_key
        payload["order_link_id"] = self.order_link_id
        return payload

    def _stable_payload(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "symbol": self.symbol,
            "category": self.category,
            "intent": self.intent.value,
            "environment": self.environment.value,
            "quantity": str(self.quantity),
            "reference_price": str(self.reference_price),
            "limit_price": None if self.limit_price is None else str(self.limit_price),
            "order_type": self.order_type.value,
            "time_in_force": self.time_in_force.value,
            "reduce_only": self.reduce_only,
            "portfolio_snapshot_id": self.portfolio_snapshot_id,
            "risk_evidence_id": self.risk_evidence_id,
            "security_evidence_id": self.security_evidence_id,
            "decision_evidence_id": self.decision_evidence_id,
            "constraints_evidence_id": self.constraints.evidence_id,
            "cost_evidence_id": self.costs.evidence_id,
            "expires_at_ms": self.expires_at_ms,
        }


@dataclass(frozen=True, slots=True)
class AdapterPreview:
    """Non-executing adapter normalization result."""

    adapter_id: str
    environment: ExecutionEnvironment
    normalized_symbol: str
    normalized_quantity: Decimal
    normalized_price: Decimal | None
    idempotency_key: str
    warnings: tuple[str, ...] = ()
    write_permitted: bool = False

    def __post_init__(self) -> None:
        if not self.adapter_id.strip():
            raise ValueError("adapter_id must not be empty")
        if self.write_permitted:
            raise ValueError("adapter previews cannot permit writes")


@runtime_checkable
class ExecutionAdapterBoundary(Protocol):
    """Read/preview-only boundary implemented by paper/future exchange adapters."""

    adapter_id: str
    environment: ExecutionEnvironment

    def preview(self, intent: CanonicalExecutionIntent) -> AdapterPreview:
        """Normalize/validate without sending any order."""
        ...
