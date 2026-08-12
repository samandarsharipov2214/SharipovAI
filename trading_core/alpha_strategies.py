"""Pre-registered non-benchmark strategy candidates for Alpha research.

These strategies are research hypotheses, not production trading policy. They are
kept separate from ``strategies.py`` so benchmark baselines cannot be relabeled as
alpha candidates.
"""
from __future__ import annotations

import math
import statistics
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from typing import Any

from .models import MarketEvent, PortfolioSnapshot, Side, Signal


@dataclass(frozen=True, slots=True)
class RegimeFilteredBreakoutConfig:
    """Frozen parameters for the first real SharipovAI alpha hypothesis.

    Economic hypothesis: a breakout is more likely to persist when it occurs
    after an established positive trend, in a non-dormant but non-extreme
    volatility regime, and with volume confirmation. Cooldown and time-based exits
    are intended to reduce repeated entries during choppy regimes.
    """

    breakout_window: int = 24
    exit_window: int = 10
    volatility_window: int = 32
    trend_window: int = 16
    volume_window: int = 24
    breakout_buffer_percent: float = 0.05
    minimum_volatility_percent: float = 0.10
    maximum_volatility_percent: float = 2.50
    minimum_trend_percent: float = 0.20
    volume_multiplier: float = 1.10
    maximum_hold_bars: int = 48
    cooldown_bars: int = 8
    requested_risk_percent: float = 1.0
    stop_loss_percent: float = 1.5

    def __post_init__(self) -> None:
        integer_fields = {
            "breakout_window": self.breakout_window,
            "exit_window": self.exit_window,
            "volatility_window": self.volatility_window,
            "trend_window": self.trend_window,
            "volume_window": self.volume_window,
            "maximum_hold_bars": self.maximum_hold_bars,
            "cooldown_bars": self.cooldown_bars,
        }
        for name, value in integer_fields.items():
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if self.exit_window > self.breakout_window:
            raise ValueError("exit_window cannot exceed breakout_window")
        if self.trend_window > self.breakout_window:
            raise ValueError("trend_window cannot exceed breakout_window")
        numeric_fields = {
            "breakout_buffer_percent": self.breakout_buffer_percent,
            "minimum_volatility_percent": self.minimum_volatility_percent,
            "maximum_volatility_percent": self.maximum_volatility_percent,
            "minimum_trend_percent": self.minimum_trend_percent,
            "volume_multiplier": self.volume_multiplier,
            "requested_risk_percent": self.requested_risk_percent,
            "stop_loss_percent": self.stop_loss_percent,
        }
        for name, value in numeric_fields.items():
            if isinstance(value, bool) or not math.isfinite(float(value)):
                raise ValueError(f"{name} must be finite")
        if not 0 <= self.breakout_buffer_percent <= 5:
            raise ValueError("breakout_buffer_percent must be within 0..5")
        if not 0 <= self.minimum_volatility_percent < self.maximum_volatility_percent <= 25:
            raise ValueError("volatility bounds must satisfy 0 <= min < max <= 25")
        if not 0 <= self.minimum_trend_percent <= 25:
            raise ValueError("minimum_trend_percent must be within 0..25")
        if not 0.1 <= self.volume_multiplier <= 10:
            raise ValueError("volume_multiplier must be within 0.1..10")
        if not 0 < self.requested_risk_percent <= 5:
            raise ValueError("requested_risk_percent must be within 0..5")
        if not 0 < self.stop_loss_percent <= 25:
            raise ValueError("stop_loss_percent must be within 0..25")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RegimeFilteredBreakoutStrategy:
    """Long-only volatility/volume/trend filtered breakout candidate.

    The signal uses only the current completed observation plus history that was
    already available. With close-derived historical bars, canonical backtesting
    defers the resulting order to the next event for the same symbol.
    """

    candidate_name = "regime_filtered_breakout_v1"
    benchmark = False
    hypothesis = (
        "breakouts on liquid crypto spot markets persist more reliably when "
        "preceded by positive trend persistence, moderate realized volatility, "
        "and above-normal volume"
    )

    def __init__(self, config: RegimeFilteredBreakoutConfig | None = None) -> None:
        self.config = config or RegimeFilteredBreakoutConfig()
        history_size = max(
            self.config.breakout_window,
            self.config.volatility_window + 1,
            self.config.trend_window,
            self.config.exit_window,
        )
        self._prices: dict[str, deque[float]] = defaultdict(
            lambda: deque(maxlen=history_size)
        )
        self._volumes: dict[str, deque[float]] = defaultdict(
            lambda: deque(maxlen=self.config.volume_window)
        )
        self._held_bars: dict[str, int] = defaultdict(int)
        self._cooldown_remaining: dict[str, int] = defaultdict(int)
        self._was_in_position: dict[str, bool] = defaultdict(bool)

    def on_market(
        self,
        event: MarketEvent,
        portfolio: PortfolioSnapshot,
    ) -> Signal | None:
        _validate_research_event(event)
        symbol = event.symbol
        price = event.mid
        prices = self._prices[symbol]
        volumes = self._volumes[symbol]
        prior_prices = tuple(prices)
        prior_volumes = tuple(volumes)
        in_position = symbol in portfolio.positions
        was_in_position = self._was_in_position[symbol]

        if in_position:
            self._held_bars[symbol] = self._held_bars[symbol] + 1 if was_in_position else 1
        else:
            self._held_bars[symbol] = 0
            if was_in_position:
                self._cooldown_remaining[symbol] = self.config.cooldown_bars
            elif self._cooldown_remaining[symbol] > 0:
                self._cooldown_remaining[symbol] -= 1

        signal: Signal | None = None
        if in_position:
            signal = self._exit_signal(
                event=event,
                prior_prices=prior_prices,
                held_bars=self._held_bars[symbol],
                entry_price=portfolio.positions[symbol].entry_price,
            )
        elif self._cooldown_remaining[symbol] == 0:
            signal = self._entry_signal(
                event=event,
                prior_prices=prior_prices,
                prior_volumes=prior_volumes,
            )

        prices.append(price)
        volumes.append(float(event.volume))
        self._was_in_position[symbol] = in_position
        return signal

    def _entry_signal(
        self,
        *,
        event: MarketEvent,
        prior_prices: tuple[float, ...],
        prior_volumes: tuple[float, ...],
    ) -> Signal | None:
        required_prices = max(
            self.config.breakout_window,
            self.config.volatility_window + 1,
            self.config.trend_window,
        )
        if len(prior_prices) < required_prices:
            return None
        if len(prior_volumes) < self.config.volume_window:
            return None

        breakout_high = max(prior_prices[-self.config.breakout_window :])
        breakout_level = breakout_high * (1.0 + self.config.breakout_buffer_percent / 100.0)
        if event.mid <= breakout_level:
            return None

        volatility = _realized_volatility_percent(
            prior_prices[-(self.config.volatility_window + 1) :]
        )
        if not self.config.minimum_volatility_percent <= volatility <= self.config.maximum_volatility_percent:
            return None

        trend_anchor = prior_prices[-self.config.trend_window]
        trend_percent = (event.mid / trend_anchor - 1.0) * 100.0
        if trend_percent < self.config.minimum_trend_percent:
            return None

        average_volume = statistics.fmean(prior_volumes[-self.config.volume_window :])
        if average_volume <= 0:
            return None
        if float(event.volume) < average_volume * self.config.volume_multiplier:
            return None

        return Signal(
            Side.BUY,
            requested_risk_percent=self.config.requested_risk_percent,
            stop_loss_percent=self.config.stop_loss_percent,
            reason="alpha_regime_breakout_entry",
            liquidity_role="taker",
        )

    def _exit_signal(
        self,
        *,
        event: MarketEvent,
        prior_prices: tuple[float, ...],
        held_bars: int,
        entry_price: float,
    ) -> Signal | None:
        stop_level = entry_price * (1.0 - self.config.stop_loss_percent / 100.0)
        if event.mid <= stop_level:
            return Signal(Side.SELL, reason="alpha_regime_breakout_stop", liquidity_role="taker")
        if held_bars >= self.config.maximum_hold_bars:
            return Signal(Side.SELL, reason="alpha_regime_breakout_time_exit", liquidity_role="taker")
        if len(prior_prices) >= self.config.exit_window:
            exit_floor = min(prior_prices[-self.config.exit_window :])
            if event.mid < exit_floor:
                return Signal(Side.SELL, reason="alpha_regime_breakout_channel_exit", liquidity_role="taker")
        return None


def _validate_research_event(event: MarketEvent) -> None:
    metadata = event.metadata
    if str(metadata.get("market_type") or "").strip().lower() != "spot":
        raise ValueError("regime_filtered_breakout_v1 requires spot market events")
    if str(metadata.get("timestamp_semantics") or "").strip().lower() != "bar_close":
        raise ValueError("regime_filtered_breakout_v1 requires bar_close timestamps")
    if str(metadata.get("price_source") or "").strip().lower() != "synthetic_from_close":
        raise ValueError("regime_filtered_breakout_v1 requires close-derived price events")
    if event.volume is None:
        raise ValueError("regime_filtered_breakout_v1 requires volume")
    volume = float(event.volume)
    if not math.isfinite(volume) or volume < 0:
        raise ValueError("regime_filtered_breakout_v1 requires finite non-negative volume")


def _realized_volatility_percent(prices: tuple[float, ...]) -> float:
    if len(prices) < 3:
        return 0.0
    returns = [
        current / previous - 1.0
        for previous, current in zip(prices, prices[1:])
        if previous > 0
    ]
    if len(returns) < 2:
        return 0.0
    return statistics.stdev(returns) * 100.0


__all__ = ["RegimeFilteredBreakoutConfig", "RegimeFilteredBreakoutStrategy"]
