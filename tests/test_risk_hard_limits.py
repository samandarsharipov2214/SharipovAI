from __future__ import annotations

from risk_engine import RiskEngine, RiskInput, RiskLevel, RiskLimits


def _safe(**changes) -> RiskInput:
    values = {
        "portfolio_drawdown": 2.0,
        "portfolio_exposure": 20.0,
        "asset_exposure": 10.0,
        "volatility_score": 20.0,
        "liquidity_score": 90.0,
        "correlation_score": 20.0,
        "daily_loss_percent": 0.0,
        "weekly_drawdown_percent": 0.0,
        "correlated_exposure": 10.0,
        "open_positions": 1,
        "max_open_positions": 5,
        "stale_data": False,
        "kill_switch_active": False,
        "instrument_valid": True,
    }
    values.update(changes)
    return RiskInput(**values)


def test_stale_data_and_kill_switch_are_absolute_blocks() -> None:
    stale = RiskEngine().evaluate(_safe(stale_data=True))
    killed = RiskEngine().evaluate(_safe(kill_switch_active=True))

    assert stale.allowed is False
    assert "stale_market_data" in stale.hard_blocks
    assert stale.position_size_multiplier == 0.0
    assert killed.allowed is False
    assert "execution_kill_switch" in killed.hard_blocks


def test_daily_weekly_and_correlation_limits_block() -> None:
    daily = RiskEngine().evaluate(_safe(daily_loss_percent=2.0))
    weekly = RiskEngine().evaluate(_safe(weekly_drawdown_percent=5.0))
    correlated = RiskEngine().evaluate(_safe(correlated_exposure=35.0))

    assert "daily_loss_limit" in daily.hard_blocks
    assert "weekly_drawdown_limit" in weekly.hard_blocks
    assert "correlated_exposure_limit" in correlated.hard_blocks
    assert not daily.allowed and not weekly.allowed and not correlated.allowed


def test_position_limit_and_liquidity_floor_block() -> None:
    positions = RiskEngine().evaluate(_safe(open_positions=5))
    liquidity = RiskEngine().evaluate(_safe(liquidity_score=20.0))

    assert "open_position_limit" in positions.hard_blocks
    assert "liquidity_floor" in liquidity.hard_blocks


def test_soft_risk_level_scales_position_without_overriding_hard_limits() -> None:
    low = RiskEngine().evaluate(_safe())
    medium = RiskEngine().evaluate(
        _safe(
            portfolio_drawdown=6.0,
            portfolio_exposure=45.0,
            asset_exposure=20.0,
            volatility_score=55.0,
            liquidity_score=60.0,
            correlation_score=50.0,
        )
    )
    research_limits = RiskLimits(
        max_portfolio_drawdown_percent=100.0,
        max_daily_loss_percent=100.0,
        max_weekly_drawdown_percent=100.0,
        max_portfolio_exposure_percent=100.0,
        max_asset_exposure_percent=100.0,
        max_correlated_exposure_percent=100.0,
        minimum_liquidity_score=1.0,
        max_open_positions=100,
    )
    high = RiskEngine(research_limits).evaluate(
        _safe(
            portfolio_drawdown=70.0,
            portfolio_exposure=70.0,
            asset_exposure=70.0,
            volatility_score=70.0,
            liquidity_score=30.0,
            correlation_score=70.0,
        )
    )

    assert low.risk_level is RiskLevel.LOW
    assert low.position_size_multiplier == 1.0
    assert medium.risk_level is RiskLevel.MEDIUM
    assert medium.allowed is True
    assert medium.position_size_multiplier == 0.6
    assert high.risk_level is RiskLevel.HIGH
    assert high.allowed is True
    assert high.position_size_multiplier == 0.25
