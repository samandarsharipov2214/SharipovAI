"""Cross-module safety contract for canonical capital and hard-risk defaults."""
from __future__ import annotations

from capital_allocation import CapitalAllocationPolicy
from risk_engine import RiskLimits


def test_default_allocator_limits_do_not_exceed_hard_risk_limits() -> None:
    """Equivalent allocation caps must stay at or inside hard risk boundaries.

    Capital allocation executes before the hard Risk Engine gate in research and
    Paper flows.  A future configuration drift must therefore never make the
    allocator more permissive than the hard risk policy for the same exposure
    concept.
    """

    allocation = CapitalAllocationPolicy()
    hard = RiskLimits()

    assert allocation.max_total_exposure_percent <= hard.max_portfolio_exposure_percent
    assert allocation.max_position_percent <= hard.max_asset_exposure_percent
    assert allocation.max_symbol_exposure_percent <= hard.max_asset_exposure_percent
    assert allocation.max_correlated_exposure_percent <= hard.max_correlated_exposure_percent
    assert allocation.max_daily_loss_percent <= hard.max_daily_loss_percent


def test_default_risk_per_trade_is_tighter_than_single_asset_exposure_cap() -> None:
    """Per-trade loss budget must remain materially below concentration caps."""

    allocation = CapitalAllocationPolicy()
    hard = RiskLimits()

    assert 0 < allocation.max_risk_per_trade_percent < hard.max_asset_exposure_percent
