"""Mean Reversion Strategy for SharipovAI - RSI-based counter-trend trading.

This strategy identifies overbought/oversold conditions using RSI and trades
against extreme moves, expecting price to revert to mean.

Best used in: RANGE market regimes (low volatility, sideways movement)
Avoid in: TREND or HIGH_VOLATILITY regimes
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence


class MeanReversionStrategy:
    """RSI-based mean reversion with Bollinger Bands confirmation."""

    def __init__(
        self,
        rsi_period: int = 14,
        oversold_threshold: float = 30.0,
        overbought_threshold: float = 70.0,
        bb_period: int = 20,
        bb_std_dev: float = 2.0,
        min_confidence: float = 60.0,
    ) -> None:
        self.rsi_period = rsi_period
        self.oversold_threshold = oversold_threshold
        self.overbought_threshold = overbought_threshold
        self.bb_period = bb_period
        self.bb_std_dev = bb_std_dev
        self.min_confidence = min_confidence

    def calculate_rsi(self, prices: Sequence[float]) -> float | None:
        """Calculate RSI from price series."""
        if len(prices) < self.rsi_period + 1:
            return None
        
        gains = []
        losses = []
        for i in range(1, len(prices)):
            change = prices[i] - prices[i - 1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
        
        if len(gains) < self.rsi_period:
            return None
        
        avg_gain = sum(gains[-self.rsi_period:]) / self.rsi_period
        avg_loss = sum(losses[-self.rsi_period:]) / self.rsi_period
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def calculate_bollinger_bands(
        self, prices: Sequence[float]
    ) -> tuple[float, float, float] | None:
        """Calculate Bollinger Bands: (lower, middle, upper)."""
        if len(prices) < self.bb_period:
            return None
        
        recent = prices[-self.bb_period:]
        middle = sum(recent) / len(recent)
        
        variance = sum((p - middle) ** 2 for p in recent) / len(recent)
        std_dev = math.sqrt(variance)
        
        lower = middle - (self.bb_std_dev * std_dev)
        upper = middle + (self.bb_std_dev * std_dev)
        
        return (lower, middle, upper)

    def signal(
        self,
        symbol: str,
        prices: Sequence[float],
        volumes: Sequence[float] | None = None,
        regime: str = "unknown",
    ) -> dict[str, Any]:
        """Generate trading signal based on RSI + Bollinger Bands.
        
        Returns:
            dict with keys: action, confidence, rationale, indicators
        """
        # Avoid trading in strong trends
        if regime in {"TREND", "HIGH_VOLATILITY"}:
            return {
                "action": "WAIT",
                "confidence": 0.0,
                "rationale": f"Mean reversion disabled in {regime} regime",
                "indicators": {},
            }
        
        rsi = self.calculate_rsi(prices)
        bb = self.calculate_bollinger_bands(prices)
        
        if rsi is None or bb is None:
            return {
                "action": "WAIT",
                "confidence": 0.0,
                "rationale": "Insufficient data for indicator calculation",
                "indicators": {"rsi": rsi, "bollinger_bands": bb},
            }
        
        lower_bb, middle_bb, upper_bb = bb
        current_price = prices[-1]
        
        # Calculate confidence based on multiple confirmations
        confidence = 50.0
        signals = []
        
        # RSI signal
        rsi_signal = None
        if rsi < self.oversold_threshold:
            rsi_signal = "BUY"
            confidence += (self.oversold_threshold - rsi) * 0.5
            signals.append(f"RSI oversold at {rsi:.1f}")
        elif rsi > self.overbought_threshold:
            rsi_signal = "SELL"
            confidence += (rsi - self.overbought_threshold) * 0.5
            signals.append(f"RSI overbought at {rsi:.1f}")
        
        # Bollinger Bands signal
        bb_signal = None
        if current_price < lower_bb:
            bb_signal = "BUY"
            distance_pct = (lower_bb - current_price) / lower_bb * 100
            confidence += min(distance_pct * 2, 15)
            signals.append(f"Price {distance_pct:.2f}% below lower BB")
        elif current_price > upper_bb:
            bb_signal = "SELL"
            distance_pct = (current_price - upper_bb) / upper_bb * 100
            confidence += min(distance_pct * 2, 15)
            signals.append(f"Price {distance_pct:.2f}% above upper BB")
        
        # Determine final action
        action = "WAIT"
        rationale_parts = []
        
        if rsi_signal == bb_signal and rsi_signal is not None:
            # Strong confirmation: both indicators agree
            action = rsi_signal
            confidence = min(confidence, 95.0)
            rationale_parts.append("RSI and Bollinger Bands confirm")
        elif rsi_signal is not None and bb_signal is None:
            # Moderate signal: RSI only, but price near band
            if rsi_signal == "BUY" and current_price <= middle_bb:
                action = "BUY"
                confidence = min(confidence * 0.8, 75.0)
                rationale_parts.append("RSI signal with price at/below middle band")
            elif rsi_signal == "SELL" and current_price >= middle_bb:
                action = "SELL"
                confidence = min(confidence * 0.8, 75.0)
                rationale_parts.append("RSI signal with price at/above middle band")
        
        if confidence < self.min_confidence:
            action = "WAIT"
            rationale_parts.append(f"Confidence {confidence:.1f}% below threshold {self.min_confidence}%")
        
        rationale = "; ".join(signals + rationale_parts) if signals else "No clear signal"
        
        return {
            "action": action,
            "confidence": round(confidence, 2),
            "rationale": rationale[:500],
            "indicators": {
                "rsi": round(rsi, 2),
                "bollinger_lower": round(lower_bb, 4),
                "bollinger_middle": round(middle_bb, 4),
                "bollinger_upper": round(upper_bb, 4),
                "price_position": (current_price - lower_bb) / (upper_bb - lower_bb) if upper_bb != lower_bb else 0.5,
            },
            "strategy_type": "mean_reversion",
            "regime_suitable": regime == "RANGE",
        }

    def get_parameters(self) -> dict[str, Any]:
        """Return strategy parameters for logging/configuration."""
        return {
            "rsi_period": self.rsi_period,
            "oversold_threshold": self.oversold_threshold,
            "overbought_threshold": self.overbought_threshold,
            "bb_period": self.bb_period,
            "bb_std_dev": self.bb_std_dev,
            "min_confidence": self.min_confidence,
        }


# Integration helper for SharipovAI council system
def create_mean_reversion_opinion(
    symbol: str,
    prices: list[float],
    volumes: list[float] | None = None,
    regime: str = "RANGE",
) -> dict[str, Any]:
    """Create an opinion payload compatible with SharipovAI council system."""
    strategy = MeanReversionStrategy()
    result = strategy.signal(symbol, prices, volumes, regime)
    
    action_map = {"BUY": "BUY", "SELL": "SELL", "WAIT": "WAIT"}
    action = action_map.get(result["action"], "WAIT")
    
    return {
        "agent_id": "mean_reversion_strategy",
        "action": action,
        "confidence": result["confidence"],
        "evidence_score": result["confidence"] * 0.9,  # Slight discount vs pure AI
        "risk_score": 100.0 - result["confidence"],
        "rationale": result["rationale"],
        "evidence_class": "technical_indicator",
        "verified_market_data": True,
        "learning_eligible": True,
        "evidence_eligible": True,
        "reputation_eligible": True,
        "metadata": {
            "strategy": "mean_reversion",
            "indicators": result.get("indicators", {}),
            "regime": regime,
        },
    }


if __name__ == "__main__":
    # Example usage
    import random
    
    # Simulate price data (sideways market)
    base_price = 50000
    prices = [base_price + random.uniform(-500, 500) for _ in range(50)]
    
    strategy = MeanReversionStrategy()
    result = strategy.signal("BTCUSDT", prices, regime="RANGE")
    
    print(f"Action: {result['action']}")
    print(f"Confidence: {result['confidence']}%")
    print(f"Rationale: {result['rationale']}")
    print(f"Indicators: {result['indicators']}")
