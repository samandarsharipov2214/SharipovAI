"""Bounded Paper/Testnet shadow planning over one canonical candidate evidence set."""
from __future__ import annotations

import hashlib
import math
import os
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from exchange_connector.bybit_reference_data import (
    BybitTradingReferenceClient,
    TradingReferenceSnapshot,
)
from trading_candidate import TradingCandidate, TradingCategory, TradingEnvironment


@dataclass(frozen=True, slots=True)
class ShadowModePolicy:
    maximum_testnet_notional_usdt: float = 25.0
    maximum_trade_age_ms: int = 5_000
    require_dynamic_reference_data: bool = True

    @classmethod
    def from_environment(cls) -> "ShadowModePolicy":
        configured = _finite_env("SHADOW_TESTNET_MAX_NOTIONAL_USDT", 25.0)
        # This branch cannot raise the Testnet cap above 25 USDT through environment.
        maximum = min(max(configured, 1.0), 25.0)
        age = int(min(max(_finite_env("SHADOW_MAX_TRADE_AGE_MS", 5_000.0), 1_000), 5_000))
        return cls(
            maximum_testnet_notional_usdt=maximum,
            maximum_trade_age_ms=age,
            require_dynamic_reference_data=True,
        )


@dataclass(frozen=True, slots=True)
class ShadowOrderPlan:
    shadow_pair_id: str
    paper_trade_id: str
    source_candidate_id: str
    testnet_candidate_id: str
    symbol: str
    side: str
    reference_price: float
    paper_quantity: float
    testnet_quantity: float
    testnet_notional: float
    maker_fee_rate: float
    taker_fee_rate: float
    quantity_step: float
    minimum_quantity: float
    minimum_notional: float
    maximum_market_quantity: float
    reference_received_at_ms: int
    reference_expires_at_ms: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ShadowModePlanner:
    """Create a tiny Testnet twin without changing Paper sizing or candidate evidence."""

    def __init__(
        self,
        reference_client: BybitTradingReferenceClient | None = None,
        *,
        policy: ShadowModePolicy | None = None,
    ) -> None:
        self.reference_client = reference_client or BybitTradingReferenceClient()
        self.policy = policy or ShadowModePolicy.from_environment()

    def plan(
        self,
        *,
        paper_trade: Mapping[str, Any],
        testnet_candidate: TradingCandidate,
        execution_max_notional: float,
        now_ms: int,
    ) -> ShadowOrderPlan:
        if testnet_candidate.environment is not TradingEnvironment.TESTNET:
            raise ValueError("shadow candidate must target Testnet")
        if testnet_candidate.category is not TradingCategory.SPOT:
            raise ValueError("shadow mode currently permits spot only")
        trade_id = _required(paper_trade.get("trade_id"), "paper trade_id")
        created_at_ms = _positive_int(paper_trade.get("created_at_ms"), "created_at_ms")
        if now_ms < created_at_ms:
            raise ValueError("paper trade timestamp is in the future")
        if now_ms - created_at_ms > self.policy.maximum_trade_age_ms:
            raise ValueError("paper trade is too old for shadow mirroring")
        source_candidate_id = _source_candidate_id(paper_trade)
        paper_quantity = _positive(paper_trade.get("quantity"), "paper quantity")
        reference_price = _positive(paper_trade.get("price"), "paper price")
        hard_cap = min(
            _positive(execution_max_notional, "execution max notional"),
            self.policy.maximum_testnet_notional_usdt,
        )
        snapshot = self.reference_client.get(
            testnet_candidate.symbol,
            category=testnet_candidate.category.value,
            allow_network=self.policy.require_dynamic_reference_data,
            now_ms=now_ms,
        )
        _validate_snapshot(snapshot, candidate=testnet_candidate, now_ms=now_ms)
        quantity = snapshot.instrument.normalize_quantity(
            requested_quantity=paper_quantity,
            reference_price=reference_price,
            maximum_notional=hard_cap,
        )
        notional = quantity * reference_price
        pair_id = "shadow_" + hashlib.sha256(
            f"{trade_id}:{source_candidate_id}:{testnet_candidate.candidate_id}".encode("utf-8")
        ).hexdigest()[:32]
        return ShadowOrderPlan(
            shadow_pair_id=pair_id,
            paper_trade_id=trade_id,
            source_candidate_id=source_candidate_id,
            testnet_candidate_id=testnet_candidate.candidate_id,
            symbol=testnet_candidate.symbol,
            side=testnet_candidate.side.value.upper(),
            reference_price=reference_price,
            paper_quantity=paper_quantity,
            testnet_quantity=quantity,
            testnet_notional=notional,
            maker_fee_rate=snapshot.fee.maker_fee_rate,
            taker_fee_rate=snapshot.fee.taker_fee_rate,
            quantity_step=snapshot.instrument.quantity_step,
            minimum_quantity=snapshot.instrument.minimum_quantity,
            minimum_notional=snapshot.instrument.minimum_notional,
            maximum_market_quantity=snapshot.instrument.maximum_market_quantity,
            reference_received_at_ms=snapshot.received_at_ms,
            reference_expires_at_ms=snapshot.expires_at_ms,
        )


def _validate_snapshot(
    snapshot: TradingReferenceSnapshot,
    *,
    candidate: TradingCandidate,
    now_ms: int,
) -> None:
    if snapshot.environment != "sandbox":
        raise RuntimeError("shadow execution requires a Testnet reference snapshot")
    if snapshot.symbol != candidate.symbol or snapshot.category != candidate.category.value:
        raise RuntimeError("Bybit reference snapshot does not match candidate")
    if snapshot.expires_at_ms < now_ms:
        raise RuntimeError("Bybit reference snapshot is stale")
    if snapshot.instrument.status != "Trading":
        raise RuntimeError("Bybit instrument is not Trading")


def _source_candidate_id(trade: Mapping[str, Any]) -> str:
    raw = trade.get("execution_candidate")
    if isinstance(raw, Mapping) and raw.get("candidate_id"):
        return _required(raw.get("candidate_id"), "source candidate_id")
    return _required(trade.get("candidate_id"), "source candidate_id")


def _required(value: Any, name: str) -> str:
    clean = str(value or "").strip()
    if not clean:
        raise ValueError(f"{name} is required")
    return clean


def _positive(value: Any, name: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError(f"{name} must be positive and finite")
    return parsed


def _positive_int(value: Any, name: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _finite_env(name: str, default: float) -> float:
    try:
        parsed = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


__all__ = ["ShadowModePlanner", "ShadowModePolicy", "ShadowOrderPlan"]
