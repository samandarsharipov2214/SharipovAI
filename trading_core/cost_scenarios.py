"""Deterministic transaction-cost scenario evaluation with explicit provenance."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, replace
from typing import Callable, Iterable, Sequence

from .backtest import EventDrivenBacktester, Strategy
from .models import BacktestConfig, BacktestResult, MarketEvent


@dataclass(frozen=True, slots=True)
class TransactionCostScenario:
    """One immutable research cost assumption set with source provenance.

    Spread and funding remain point-in-time properties of ``MarketEvent``. This
    contract records where those inputs came from while fee/slippage/impact
    assumptions are applied through ``BacktestConfig``.
    """

    scenario_id: str
    fee_rate: float
    maker_fee_rate: float
    slippage_bps: float
    market_impact_bps: float
    fee_source: str
    spread_source: str
    slippage_source: str
    funding_source: str

    def __post_init__(self) -> None:
        if not self.scenario_id.strip():
            raise ValueError("scenario_id must not be blank")
        for name in ("fee_source", "spread_source", "slippage_source", "funding_source"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} must not be blank")
        for name, value, maximum in (
            ("fee_rate", self.fee_rate, 0.05),
            ("maker_fee_rate", self.maker_fee_rate, 0.05),
            ("slippage_bps", self.slippage_bps, 1_000.0),
            ("market_impact_bps", self.market_impact_bps, 10_000.0),
        ):
            if not math.isfinite(value) or not 0 <= value <= maximum:
                raise ValueError(f"{name} must be within 0..{maximum}")

    def apply(self, base: BacktestConfig) -> BacktestConfig:
        return replace(
            base,
            fee_rate=float(self.fee_rate),
            maker_fee_rate=float(self.maker_fee_rate),
            slippage_bps=float(self.slippage_bps),
            market_impact_bps=float(self.market_impact_bps),
        )

    def provenance(self) -> dict[str, object]:
        return {
            **asdict(self),
            "spread_input": "market_event.bid_ask",
            "funding_input": "market_event.funding_rate",
        }


@dataclass(frozen=True, slots=True)
class TransactionCostScenarioResult:
    scenario_id: str
    result: BacktestResult
    provenance: dict[str, object]


def evaluate_transaction_cost_scenarios(
    events: Sequence[MarketEvent] | Iterable[MarketEvent],
    *,
    strategy_factory: Callable[[], Strategy],
    scenarios: Sequence[TransactionCostScenario],
    base_config: BacktestConfig | None = None,
) -> tuple[TransactionCostScenarioResult, ...]:
    """Run the same immutable event sample under explicit cost assumptions."""

    ordered = tuple(events)
    if not ordered:
        raise ValueError("transaction-cost scenarios require market events")
    if not scenarios:
        raise ValueError("at least one transaction-cost scenario is required")

    ids = [scenario.scenario_id for scenario in scenarios]
    if len(ids) != len(set(ids)):
        raise ValueError("transaction-cost scenario_id values must be unique")

    base = base_config or BacktestConfig()
    results: list[TransactionCostScenarioResult] = []
    for scenario in scenarios:
        strategy = strategy_factory()
        result = EventDrivenBacktester(scenario.apply(base)).run(ordered, strategy)
        results.append(
            TransactionCostScenarioResult(
                scenario_id=scenario.scenario_id,
                result=result,
                provenance=scenario.provenance(),
            )
        )
    return tuple(results)


__all__ = [
    "TransactionCostScenario",
    "TransactionCostScenarioResult",
    "evaluate_transaction_cost_scenarios",
]
