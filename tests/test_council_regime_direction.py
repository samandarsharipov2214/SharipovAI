from __future__ import annotations

from autonomous_trading.council_provider import _meta_regime
from trading_candidate import MarketRegime


def test_trend_regime_preserves_bull_and_bear_direction() -> None:
    assert _meta_regime(MarketRegime.TREND, change=2.5) == "bull"
    assert _meta_regime(MarketRegime.TREND, change=-2.5) == "bear"
    assert _meta_regime(MarketRegime.TREND, change=0.0) == "sideways"


def test_non_trend_regimes_keep_existing_semantics() -> None:
    assert _meta_regime(MarketRegime.RANGE, change=-2.0) == "sideways"
    assert _meta_regime(MarketRegime.HIGH_VOLATILITY, change=-9.0) == "high_volatility"
    assert _meta_regime(MarketRegime.ILLIQUID, change=-2.0) == "unknown"
