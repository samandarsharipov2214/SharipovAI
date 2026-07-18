"""Deterministic correlation-aware sizing for bounded Testnet execution."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

_SYMBOL_RE = re.compile(r"^[A-Z0-9]{3,32}$")


@dataclass(frozen=True, slots=True)
class CapitalPolicy:
    risk_budget_fraction: float = 0.0025
    maximum_position_fraction: float = 0.05
    maximum_cluster_fraction: float = 0.10
    volatility_floor: float = 0.005
    correlation_threshold: float = 0.70
    maximum_notional_usdt: float = 50.0

    def __post_init__(self) -> None:
        values = {
            "risk_budget_fraction": self.risk_budget_fraction,
            "maximum_position_fraction": self.maximum_position_fraction,
            "maximum_cluster_fraction": self.maximum_cluster_fraction,
            "volatility_floor": self.volatility_floor,
            "correlation_threshold": self.correlation_threshold,
            "maximum_notional_usdt": self.maximum_notional_usdt,
        }
        parsed = {key: _required_finite(value, key) for key, value in values.items()}
        if not 0 < parsed["risk_budget_fraction"] <= 0.05:
            raise ValueError("risk_budget_fraction must be within (0, 0.05]")
        if not 0 < parsed["maximum_position_fraction"] <= 1:
            raise ValueError("maximum_position_fraction must be within (0, 1]")
        if not 0 < parsed["maximum_cluster_fraction"] <= 1:
            raise ValueError("maximum_cluster_fraction must be within (0, 1]")
        if not 0 < parsed["volatility_floor"] <= 1:
            raise ValueError("volatility_floor must be within (0, 1]")
        if not 0 <= parsed["correlation_threshold"] <= 1:
            raise ValueError("correlation_threshold must be within [0, 1]")
        if not 0 < parsed["maximum_notional_usdt"] <= 50:
            raise ValueError("maximum_notional_usdt must be within (0, 50]")


class CorrelationAwareCapitalEngine:
    """Returns the smallest safe notional or a fail-closed reason."""

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
        equity = _optional_finite(equity_usdt)
        stop = _optional_finite(stop_distance_fraction)
        if equity is None or stop is None or equity <= 0 or stop <= 0:
            return _blocked("invalid_equity_or_stop")
        raw_volatility = _optional_finite(realized_volatility)
        if raw_volatility is None or raw_volatility < 0:
            return _blocked("invalid_volatility")
        volatility = max(raw_volatility, self.policy.volatility_floor)
        symbol = str(proposed_symbol or "").strip().upper()
        if not _SYMBOL_RE.fullmatch(symbol):
            return _blocked("invalid_symbol")
        ceiling_input = _optional_finite(scaling_ceiling_usdt)
        if ceiling_input is None or not 0 < ceiling_input <= self.policy.maximum_notional_usdt:
            return _blocked("invalid_scaling_authority")
        if not isinstance(open_positions, Sequence) or isinstance(open_positions, (str, bytes)):
            return _blocked("invalid_positions")
        if not isinstance(correlations, Mapping):
            return _blocked("invalid_correlation_matrix")

        exposures: dict[str, float] = {}
        for position in open_positions:
            if not isinstance(position, Mapping):
                return _blocked("invalid_positions")
            position_symbol = str(position.get("symbol") or "").strip().upper()
            notional = _optional_finite(position.get("notional_usdt"))
            if not _SYMBOL_RE.fullmatch(position_symbol) or notional is None or notional < 0:
                return _blocked("invalid_positions")
            exposures[position_symbol] = exposures.get(position_symbol, 0.0) + abs(notional)

        correlations_used: dict[str, float] = {}
        missing_correlations: list[str] = []
        invalid_correlations: list[str] = []
        cluster_exposure = 0.0
        correlated_symbols: list[str] = []
        for position_symbol, exposure in sorted(exposures.items()):
            correlation = _lookup_correlation(correlations, symbol, position_symbol)
            if correlation is None:
                missing_correlations.append(position_symbol)
                continue
            if not -1 <= correlation <= 1:
                invalid_correlations.append(position_symbol)
                continue
            correlations_used[position_symbol] = correlation
            if abs(correlation) >= self.policy.correlation_threshold:
                correlated_symbols.append(position_symbol)
                cluster_exposure += exposure

        if invalid_correlations:
            return _blocked("invalid_correlation_data", invalid_correlations=invalid_correlations)
        if missing_correlations:
            return _blocked("missing_correlation_data", missing_correlations=missing_correlations)

        existing_symbol_exposure = exposures.get(symbol, 0.0)
        position_limit = equity * self.policy.maximum_position_fraction
        cluster_limit = equity * self.policy.maximum_cluster_fraction
        position_remaining = max(0.0, position_limit - existing_symbol_exposure)
        cluster_remaining = max(0.0, cluster_limit - cluster_exposure)
        risk_budget_usdt = equity * self.policy.risk_budget_fraction
        risk_notional = risk_budget_usdt / stop
        volatility_multiplier = min(1.0, self.policy.volatility_floor / volatility)
        volatility_adjusted = risk_notional * volatility_multiplier
        ceiling = min(self.policy.maximum_notional_usdt, ceiling_input)
        notional = min(volatility_adjusted, position_remaining, cluster_remaining, ceiling)

        checks = {
            "positive_size": notional > 0,
            "within_scaling_authority": notional <= ceiling,
            "within_position_limit": existing_symbol_exposure + notional <= position_limit + 1e-9,
            "within_cluster_limit": cluster_exposure + notional <= cluster_limit + 1e-9,
            "correlation_data_complete": not missing_correlations and not invalid_correlations,
        }
        failed = sorted(name for name, passed in checks.items() if not passed)
        return {
            "allowed": not failed,
            "reason": "ok" if not failed else "risk_capacity_exhausted",
            "notional_usdt": round(notional, 12) if not failed else 0.0,
            "risk_budget_usdt": round(risk_budget_usdt, 12),
            "risk_notional_usdt": round(risk_notional, 12),
            "volatility_multiplier": round(volatility_multiplier, 8),
            "position_exposure_before_usdt": round(existing_symbol_exposure, 12),
            "position_remaining_usdt": round(position_remaining, 12),
            "cluster_exposure_before_usdt": round(cluster_exposure, 12),
            "cluster_remaining_usdt": round(cluster_remaining, 12),
            "correlated_symbols": sorted(set(correlated_symbols)),
            "correlations_used": correlations_used,
            "checks": checks,
            "failed_checks": failed,
            "mainnet_enabled": False,
        }


def _lookup_correlation(
    matrix: Mapping[str, Mapping[str, float]], left: str, right: str
) -> float | None:
    if left == right:
        return 1.0
    direct = matrix.get(left)
    reverse = matrix.get(right)
    raw: Any = None
    if isinstance(direct, Mapping) and right in direct:
        raw = direct[right]
    elif isinstance(reverse, Mapping) and left in reverse:
        raw = reverse[left]
    return _optional_finite(raw)


def _blocked(reason: str, **details: Any) -> dict[str, Any]:
    return {
        "allowed": False,
        "reason": reason,
        "notional_usdt": 0.0,
        "mainnet_enabled": False,
        **details,
    }


def _required_finite(value: Any, name: str) -> float:
    parsed = _optional_finite(value)
    if parsed is None:
        raise ValueError(f"{name} must be finite")
    return parsed


def _optional_finite(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


__all__ = ["CapitalPolicy", "CorrelationAwareCapitalEngine"]
