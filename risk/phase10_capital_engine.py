"""Deterministic correlation-aware position sizing for bounded Testnet execution."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True, slots=True)
class CapitalPolicy:
    risk_budget_fraction: float = 0.0025
    maximum_position_fraction: float = 0.05
    maximum_cluster_fraction: float = 0.10
    volatility_floor: float = 0.005
    correlation_threshold: float = 0.70
    maximum_notional_usdt: float = 50.0


class CorrelationAwareCapitalEngine:
    def __init__(self, policy: CapitalPolicy | None = None) -> None:
        self.policy = policy or CapitalPolicy()

    def size(
        self,
        *,
        equity_usdt: float,
        stop_distance_fraction: float,
        realized_volatility: float,
        proposed_symbol: str,
        open_positions: Sequence[Mapping[str, Any]],
        correlations: Mapping[str, Mapping[str, float]],
        scaling_ceiling_usdt: float,
    ) -> dict[str, Any]:
        equity = _finite(equity_usdt)
        stop = _finite(stop_distance_fraction)
        volatility = max(_finite(realized_volatility), self.policy.volatility_floor)
        if equity <= 0 or stop <= 0:
            return {"allowed": False, "reason": "invalid_equity_or_stop", "notional_usdt": 0.0}
        risk_notional = equity * self.policy.risk_budget_fraction / stop
        vol_multiplier = min(1.0, self.policy.volatility_floor / volatility)
        base = min(risk_notional * vol_multiplier, equity * self.policy.maximum_position_fraction)
        cluster_exposure = 0.0
        correlated_symbols: list[str] = []
        for position in open_positions:
            symbol = str(position.get("symbol") or "")
            corr = abs(_correlation(correlations, proposed_symbol, symbol))
            if corr >= self.policy.correlation_threshold:
                correlated_symbols.append(symbol)
                cluster_exposure += abs(_finite(position.get("notional_usdt")))
        cluster_remaining = max(0.0, equity * self.policy.maximum_cluster_fraction - cluster_exposure)
        ceiling = min(self.policy.maximum_notional_usdt, max(0.0, _finite(scaling_ceiling_usdt)))
        notional = min(base, cluster_remaining, ceiling)
        checks = {
            "positive_size": notional > 0,
            "within_scaling_authority": notional <= ceiling,
            "within_position_limit": notional <= equity * self.policy.maximum_position_fraction,
            "within_cluster_limit": cluster_exposure + notional <= equity * self.policy.maximum_cluster_fraction + 1e-9,
        }
        failed = sorted(name for name, passed in checks.items() if not passed)
        return {
            "allowed": not failed,
            "notional_usdt": round(notional, 12) if not failed else 0.0,
            "risk_budget_usdt": round(equity * self.policy.risk_budget_fraction, 12),
            "volatility_multiplier": round(vol_multiplier, 8),
            "cluster_exposure_before_usdt": round(cluster_exposure, 12),
            "cluster_remaining_usdt": round(cluster_remaining, 12),
            "correlated_symbols": sorted(set(correlated_symbols)),
            "checks": checks,
            "failed_checks": failed,
            "mainnet_enabled": False,
        }


def _correlation(matrix: Mapping[str, Mapping[str, float]], left: str, right: str) -> float:
    if left == right:
        return 1.0
    direct = matrix.get(left, {}) if isinstance(matrix.get(left), Mapping) else {}
    reverse = matrix.get(right, {}) if isinstance(matrix.get(right), Mapping) else {}
    return _finite(direct.get(right, reverse.get(left, 0.0)))


def _finite(value: Any) -> float:
    try:
        parsed = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return parsed if math.isfinite(parsed) else 0.0


__all__ = ["CapitalPolicy", "CorrelationAwareCapitalEngine"]
