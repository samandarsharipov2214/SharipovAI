"""Canonical Settlement and PostTrade Review contract for Architecture V2.

This module is deliberately non-executing. It records immutable settlement facts
and derives post-trade review metrics from the actual trade side, fills and
costs. It does not infer BUY/SELL direction from PnL and grants no execution
authority.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum

from autonomous_trading.general_controller_v2 import TradingIntent


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


class PositionSide(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"


class ReviewOutcome(StrEnum):
    PROFIT = "PROFIT"
    LOSS = "LOSS"
    FLAT = "FLAT"


@dataclass(frozen=True, slots=True)
class SettlementFill:
    """Immutable aggregate fill facts for one completed paper position."""

    side: PositionSide
    quantity: Decimal
    entry_price: Decimal
    exit_price: Decimal
    entry_fee: Decimal
    exit_fee: Decimal
    realized_slippage_cost: Decimal
    opened_at_ms: int
    closed_at_ms: int
    entry_order_id: str
    exit_order_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "quantity", _positive(self.quantity, "quantity"))
        object.__setattr__(self, "entry_price", _positive(self.entry_price, "entry_price"))
        object.__setattr__(self, "exit_price", _positive(self.exit_price, "exit_price"))
        object.__setattr__(self, "entry_fee", _non_negative(self.entry_fee, "entry_fee"))
        object.__setattr__(self, "exit_fee", _non_negative(self.exit_fee, "exit_fee"))
        object.__setattr__(
            self,
            "realized_slippage_cost",
            _non_negative(self.realized_slippage_cost, "realized_slippage_cost"),
        )
        if self.opened_at_ms <= 0 or self.closed_at_ms <= 0:
            raise ValueError("timestamps must be positive")
        if self.closed_at_ms < self.opened_at_ms:
            raise ValueError("closed_at_ms must be >= opened_at_ms")
        if not self.entry_order_id.strip() or not self.exit_order_id.strip():
            raise ValueError("entry_order_id and exit_order_id must not be empty")

    @property
    def gross_pnl(self) -> Decimal:
        move = self.exit_price - self.entry_price
        if self.side is PositionSide.SHORT:
            move = -move
        return move * self.quantity

    @property
    def fees(self) -> Decimal:
        return self.entry_fee + self.exit_fee

    @property
    def net_pnl(self) -> Decimal:
        return self.gross_pnl - self.fees - self.realized_slippage_cost


@dataclass(frozen=True, slots=True)
class DecisionLineage:
    """Evidence lineage for entry and, when available, the separate exit decision.

    ``final_intent`` remains the entry/opening intent for backward compatibility.
    Exit intent is recorded independently so a SPOT long closed by SELL is never
    mistaken for a short entry or for a learning label derived from PnL.
    """

    decision_id: str
    candidate_id: str
    final_intent: TradingIntent
    contributing_agents: tuple[str, ...]
    gate_verdicts: tuple[tuple[str, str], ...]
    evidence_ids: tuple[str, ...]
    exit_decision_id: str | None = None
    exit_intent: TradingIntent | None = None
    exit_evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.final_intent is TradingIntent.WAIT:
            raise ValueError("WAIT cannot settle a completed position")
        if not self.decision_id.strip() or not self.candidate_id.strip():
            raise ValueError("decision_id and candidate_id must not be empty")
        if not self.evidence_ids:
            raise ValueError("evidence_ids must not be empty")
        has_exit_id = bool((self.exit_decision_id or "").strip())
        has_exit_intent = self.exit_intent is not None
        has_exit_evidence = bool(self.exit_evidence_ids)
        if has_exit_id or has_exit_intent or has_exit_evidence:
            if not has_exit_id or not has_exit_intent or not has_exit_evidence:
                raise ValueError("exit lineage requires exit_decision_id, exit_intent and exit_evidence_ids together")
            if self.exit_intent is TradingIntent.WAIT:
                raise ValueError("completed position exit_intent cannot be WAIT")

    @property
    def entry_intent(self) -> TradingIntent:
        return self.final_intent


@dataclass(frozen=True, slots=True)
class CounterfactualAttribution:
    """Role-aware attribution inputs for learning; never mutates policy itself."""

    direction_error: bool = False
    timing_error: bool = False
    sizing_error: bool = False
    cost_error: bool = False
    risk_error: bool = False
    evidence_error: bool = False
    controller_synthesis_error: bool = False
    notes: tuple[str, ...] = ()

    @property
    def implicated_roles(self) -> tuple[str, ...]:
        roles: list[str] = []
        if self.direction_error:
            roles.append("direction")
        if self.timing_error:
            roles.append("timing")
        if self.sizing_error:
            roles.append("portfolio_engine")
        if self.cost_error:
            roles.append("execution_costs")
        if self.risk_error:
            roles.append("risk_engine")
        if self.evidence_error:
            roles.append("evidence")
        if self.controller_synthesis_error:
            roles.append("general_controller")
        return tuple(roles)


@dataclass(frozen=True, slots=True)
class PostTradeReview:
    settlement_id: str
    symbol: str
    fill: SettlementFill
    lineage: DecisionLineage
    attribution: CounterfactualAttribution
    max_drawdown_quote: Decimal = Decimal("0")
    execution_authority: bool = False

    def __post_init__(self) -> None:
        if not self.settlement_id.strip() or not self.symbol.strip():
            raise ValueError("settlement_id and symbol must not be empty")
        object.__setattr__(
            self,
            "max_drawdown_quote",
            _non_negative(self.max_drawdown_quote, "max_drawdown_quote"),
        )
        if self.execution_authority:
            raise ValueError("post-trade review cannot grant execution authority")
        expected_entry_intent = TradingIntent.BUY if self.fill.side is PositionSide.LONG else TradingIntent.SELL
        if self.lineage.entry_intent is not expected_entry_intent:
            raise ValueError("lineage final_intent must match the actual opened position side")
        if self.lineage.exit_intent is not None:
            expected_exit_intent = TradingIntent.SELL if self.fill.side is PositionSide.LONG else TradingIntent.BUY
            if self.lineage.exit_intent is not expected_exit_intent:
                raise ValueError("lineage exit_intent must close the actual opened position side")

    @property
    def outcome(self) -> ReviewOutcome:
        pnl = self.fill.net_pnl
        if pnl > 0:
            return ReviewOutcome.PROFIT
        if pnl < 0:
            return ReviewOutcome.LOSS
        return ReviewOutcome.FLAT

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["fill"]["side"] = self.fill.side.value
        for field in (
            "quantity",
            "entry_price",
            "exit_price",
            "entry_fee",
            "exit_fee",
            "realized_slippage_cost",
        ):
            payload["fill"][field] = str(getattr(self.fill, field))
        payload["lineage"]["final_intent"] = self.lineage.final_intent.value
        payload["lineage"]["entry_intent"] = self.lineage.entry_intent.value
        payload["lineage"]["exit_intent"] = self.lineage.exit_intent.value if self.lineage.exit_intent is not None else None
        payload["lineage"]["gate_verdicts"] = dict(self.lineage.gate_verdicts)
        payload["max_drawdown_quote"] = str(self.max_drawdown_quote)
        payload["gross_pnl"] = str(self.fill.gross_pnl)
        payload["fees"] = str(self.fill.fees)
        payload["net_pnl"] = str(self.fill.net_pnl)
        payload["outcome"] = self.outcome.value
        payload["implicated_roles"] = self.attribution.implicated_roles
        payload["execution_authority"] = False
        return payload


def build_review(
    *,
    settlement_id: str,
    symbol: str,
    fill: SettlementFill,
    lineage: DecisionLineage,
    attribution: CounterfactualAttribution | None = None,
    max_drawdown_quote: Decimal | str | int | float = Decimal("0"),
) -> PostTradeReview:
    """Build one immutable, side-preserving non-executing review record."""

    return PostTradeReview(
        settlement_id=settlement_id,
        symbol=symbol.strip().upper(),
        fill=fill,
        lineage=lineage,
        attribution=attribution or CounterfactualAttribution(),
        max_drawdown_quote=_non_negative(max_drawdown_quote, "max_drawdown_quote"),
        execution_authority=False,
    )


__all__ = [
    "CounterfactualAttribution",
    "DecisionLineage",
    "PositionSide",
    "PostTradeReview",
    "ReviewOutcome",
    "SettlementFill",
    "build_review",
]
