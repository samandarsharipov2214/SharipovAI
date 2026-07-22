"""Restart-safe paper broker with deterministic fees, spread, slippage and funding."""
from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass
from typing import Any

from storage import ProjectDatabase, VersionConflict

from .costs import ExecutionCostModel, validate_market_event
from .models import MarketEvent, Side

_NAMESPACE = "paper_broker_accounts_v1"


@dataclass(frozen=True, slots=True)
class PaperBrokerConfig:
    initial_cash: float = 10_000.0
    fee_rate: float = 0.001
    maker_fee_rate: float = 0.0002
    slippage_bps: float = 2.0
    market_impact_bps: float = 15.0
    max_participation_rate: float = 0.10
    maximum_fills: int = 10_000

    def __post_init__(self) -> None:
        if not math.isfinite(self.initial_cash) or self.initial_cash <= 0:
            raise ValueError("initial_cash must be positive and finite")
        if not 100 <= self.maximum_fills <= 100_000:
            raise ValueError("maximum_fills must be within 100..100000")


class RestartSafePaperBroker:
    """Persist every paper fill atomically in ``ProjectDatabase``.

    Fill IDs are idempotency keys. A process restart reconstructs cash,
    positions, funding accrual and cost totals from the same canonical state.
    """

    def __init__(
        self,
        *,
        account_id: str = "default",
        database: ProjectDatabase | None = None,
        config: PaperBrokerConfig | None = None,
    ) -> None:
        self.account_id = _identifier(account_id, "account_id")
        self.database = database or ProjectDatabase()
        self.database.initialize()
        self.config = config or PaperBrokerConfig()
        self.costs = ExecutionCostModel(
            fee_rate=self.config.fee_rate,
            maker_fee_rate=self.config.maker_fee_rate,
            slippage_bps=self.config.slippage_bps,
            market_impact_bps=self.config.market_impact_bps,
            max_participation_rate=self.config.max_participation_rate,
        )
        self._ensure_account()

    def snapshot(self, prices: dict[str, float] | None = None) -> dict[str, Any]:
        current = self.database.get_json(_NAMESPACE, self.account_id)
        if current is None:
            raise RuntimeError("paper account state is missing")
        state = _normalize_state(current["value"], self.config)
        marks = prices or {}
        unrealized = 0.0
        for symbol, position in state["positions"].items():
            mark = float(marks.get(symbol, position["last_mark_price"]))
            unrealized += (mark - position["average_entry_price"]) * position["quantity"]
        equity = state["cash"] + sum(
            float(position["quantity"]) * float(marks.get(symbol, position["last_mark_price"]))
            for symbol, position in state["positions"].items()
        )
        return {
            **state,
            "version": int(current["version"]),
            "equity": round(equity, 10),
            "unrealized_pnl": round(unrealized, 10),
            "restart_safe": True,
            "cost_model": asdict(self.config),
        }

    def execute(
        self,
        *,
        fill_id: str,
        event: MarketEvent,
        side: Side,
        quantity: float,
        reason: str,
        liquidity_role: str = "taker",
    ) -> dict[str, Any]:
        validate_market_event(event)
        clean_fill_id = _identifier(fill_id, "fill_id")
        clean_quantity = _positive(quantity, "quantity")
        if not isinstance(side, Side):
            raise TypeError("side must be Side")

        for _ in range(5):
            current = self.database.get_json(_NAMESPACE, self.account_id)
            if current is None:
                self._ensure_account()
                continue
            state = _normalize_state(current["value"], self.config)
            existing = next(
                (item for item in state["fills"] if item.get("fill_id") == clean_fill_id),
                None,
            )
            if existing is not None:
                return {**dict(existing), "duplicate": True}

            self._apply_funding(state, event)
            cost = self.costs.estimate(
                event,
                side=side,
                quantity=clean_quantity,
                liquidity_role=liquidity_role,
            )
            fill = self._apply_fill(
                state,
                fill_id=clean_fill_id,
                event=event,
                side=side,
                quantity=clean_quantity,
                reason=_identifier(reason or "paper_signal", "reason"),
                liquidity_role=liquidity_role,
                cost=cost,
            )
            state["fills"] = state["fills"][-self.config.maximum_fills :]
            state["updated_at_ms"] = max(int(time.time() * 1000), event.timestamp_ms)
            try:
                self.database.put_json(
                    _NAMESPACE,
                    self.account_id,
                    state,
                    expected_version=int(current["version"]),
                )
                return {**fill, "duplicate": False}
            except VersionConflict:
                continue
        raise RuntimeError("paper broker state update conflicted repeatedly")

    def mark(self, event: MarketEvent) -> dict[str, Any]:
        validate_market_event(event)
        for _ in range(5):
            current = self.database.get_json(_NAMESPACE, self.account_id)
            if current is None:
                self._ensure_account()
                continue
            state = _normalize_state(current["value"], self.config)
            self._apply_funding(state, event)
            position = state["positions"].get(event.symbol)
            if position is not None:
                position["last_mark_price"] = event.mid
                position["last_mark_at_ms"] = event.timestamp_ms
            state["updated_at_ms"] = max(int(time.time() * 1000), event.timestamp_ms)
            try:
                self.database.put_json(
                    _NAMESPACE,
                    self.account_id,
                    state,
                    expected_version=int(current["version"]),
                )
                return self.snapshot({event.symbol: event.mid})
            except VersionConflict:
                continue
        raise RuntimeError("paper broker mark update conflicted repeatedly")

    def _ensure_account(self) -> None:
        if self.database.get_json(_NAMESPACE, self.account_id) is not None:
            return
        state = {
            "schema_version": 1,
            "account_id": self.account_id,
            "cash": self.config.initial_cash,
            "realized_pnl": 0.0,
            "total_fees": 0.0,
            "total_slippage": 0.0,
            "total_spread_cost": 0.0,
            "total_funding": 0.0,
            "positions": {},
            "fills": [],
            "funding_payments": [],
            "updated_at_ms": int(time.time() * 1000),
        }
        try:
            self.database.put_json(
                _NAMESPACE,
                self.account_id,
                state,
                expected_version=0,
            )
        except VersionConflict:
            pass

    def _apply_funding(self, state: dict[str, Any], event: MarketEvent) -> None:
        position = state["positions"].get(event.symbol)
        if position is None:
            return
        last_ms = int(position.get("last_funding_at_ms", position["opened_at_ms"]))
        elapsed_ms = max(0, event.timestamp_ms - last_ms)
        if elapsed_ms == 0:
            return
        interval_ms = event.funding_interval_hours * 60.0 * 60.0 * 1_000.0
        fraction = elapsed_ms / interval_ms
        amount = position["quantity"] * event.mid * event.funding_rate * fraction
        if not math.isfinite(amount):
            raise ValueError("funding calculation produced a non-finite amount")
        state["cash"] -= amount
        state["total_funding"] += amount
        position["funding_paid"] += amount
        position["last_funding_at_ms"] = event.timestamp_ms
        position["last_mark_price"] = event.mid
        state["funding_payments"].append(
            {
                "timestamp_ms": event.timestamp_ms,
                "symbol": event.symbol,
                "rate": event.funding_rate,
                "interval_fraction": fraction,
                "notional": position["quantity"] * event.mid,
                "amount": amount,
            }
        )
        state["funding_payments"] = state["funding_payments"][-self.config.maximum_fills :]

    def _apply_fill(
        self,
        state: dict[str, Any],
        *,
        fill_id: str,
        event: MarketEvent,
        side: Side,
        quantity: float,
        reason: str,
        liquidity_role: str,
        cost: Any,
    ) -> dict[str, Any]:
        positions = state["positions"]
        position = positions.get(event.symbol)
        realized = 0.0
        if side is Side.BUY:
            debit = cost.execution_price * quantity + cost.fee
            if debit > state["cash"] + 1e-9:
                raise RuntimeError("paper order exceeds available cash")
            state["cash"] -= debit
            if position is None:
                positions[event.symbol] = {
                    "symbol": event.symbol,
                    "quantity": quantity,
                    "average_entry_price": cost.execution_price,
                    "entry_fees": cost.fee,
                    "funding_paid": 0.0,
                    "opened_at_ms": event.timestamp_ms,
                    "last_funding_at_ms": event.timestamp_ms,
                    "last_mark_at_ms": event.timestamp_ms,
                    "last_mark_price": event.mid,
                }
            else:
                old_qty = float(position["quantity"])
                new_qty = old_qty + quantity
                position["average_entry_price"] = (
                    old_qty * float(position["average_entry_price"])
                    + quantity * cost.execution_price
                ) / new_qty
                position["quantity"] = new_qty
                position["entry_fees"] += cost.fee
                position["last_mark_price"] = event.mid
        else:
            if position is None or quantity > float(position["quantity"]) + 1e-12:
                raise RuntimeError("paper sell exceeds open position")
            proceeds = cost.execution_price * quantity - cost.fee
            allocated_entry_fee = float(position["entry_fees"]) * (
                quantity / float(position["quantity"])
            )
            allocated_funding = float(position["funding_paid"]) * (
                quantity / float(position["quantity"])
            )
            gross = (cost.execution_price - float(position["average_entry_price"])) * quantity
            realized = gross - allocated_entry_fee - cost.fee - allocated_funding
            state["cash"] += proceeds
            state["realized_pnl"] += realized
            remaining = float(position["quantity"]) - quantity
            if remaining <= 1e-12:
                positions.pop(event.symbol, None)
            else:
                position["quantity"] = remaining
                position["entry_fees"] -= allocated_entry_fee
                position["funding_paid"] -= allocated_funding
                position["last_mark_price"] = event.mid

        state["total_fees"] += cost.fee
        state["total_slippage"] += cost.slippage_cost
        state["total_spread_cost"] += cost.spread_cost
        fill = {
            "fill_id": fill_id,
            "timestamp_ms": event.timestamp_ms,
            "symbol": event.symbol,
            "side": side.value,
            "quantity": quantity,
            "reference_price": cost.reference_price,
            "execution_price": cost.execution_price,
            "notional": cost.execution_price * quantity,
            "fee": cost.fee,
            "fee_rate": cost.fee_rate,
            "slippage_cost": cost.slippage_cost,
            "spread_cost": cost.spread_cost,
            "effective_slippage_bps": cost.effective_slippage_bps,
            "participation_rate": cost.participation_rate,
            "funding_paid_before_fill": state["total_funding"],
            "realized_pnl": realized,
            "reason": reason,
            "liquidity_role": liquidity_role,
            "source": "restart_safe_paper_broker",
        }
        state["fills"].append(fill)
        return fill


def _normalize_state(value: Any, config: PaperBrokerConfig) -> dict[str, Any]:
    if not isinstance(value, dict) or int(value.get("schema_version", 0)) != 1:
        raise RuntimeError("paper broker state schema is invalid")
    state = dict(value)
    for name in (
        "cash",
        "realized_pnl",
        "total_fees",
        "total_slippage",
        "total_spread_cost",
        "total_funding",
    ):
        parsed = float(state.get(name, 0.0))
        if not math.isfinite(parsed):
            raise RuntimeError(f"paper broker state {name} is non-finite")
        state[name] = parsed
    if state["cash"] < -1e-8:
        raise RuntimeError("paper broker state has negative cash")
    if not isinstance(state.get("positions"), dict):
        raise RuntimeError("paper broker positions must be an object")
    if not isinstance(state.get("fills"), list):
        raise RuntimeError("paper broker fills must be a list")
    state.setdefault("funding_payments", [])
    if len(state["fills"]) > config.maximum_fills:
        state["fills"] = state["fills"][-config.maximum_fills :]
    return state


def _positive(value: Any, name: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError(f"{name} must be positive and finite")
    return parsed


def _identifier(value: Any, name: str) -> str:
    clean = str(value).strip()
    if not clean or len(clean) > 160:
        raise ValueError(f"{name} is required and must be <=160 characters")
    return clean


__all__ = ["PaperBrokerConfig", "RestartSafePaperBroker"]
