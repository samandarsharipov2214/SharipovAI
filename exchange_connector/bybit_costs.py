"""Bybit cost intelligence for SharipovAI.

Values are seeded from the user's Bybit screenshots and can be overridden later
by live Bybit API/read-only data. Rates are decimal fractions, not percent text:
0.001 means 0.10%.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FeeTier:
    """Maker/taker fee tier."""

    level: str
    maker: float
    taker: float


@dataclass(frozen=True)
class BorrowRate:
    """Hourly borrow rate for a currency."""

    symbol: str
    hourly_rate: float
    max_loan_amount: float
    current_loan_amount: float = 0.0
    utilization: float = 0.0


SPOT_FEES: tuple[FeeTier, ...] = (
    FeeTier("Обычный", 0.0010, 0.0018),
    FeeTier("VIP 1", 0.00065, 0.0014),
    FeeTier("VIP 2", 0.00060, 0.0012),
    FeeTier("VIP 3", 0.00055, 0.0010),
    FeeTier("VIP 4", 0.00040, 0.0008),
    FeeTier("VIP 5", 0.00030, 0.0007),
    FeeTier("Максимальный VIP", 0.00020, 0.0006),
)

FUTURES_FEES: tuple[FeeTier, ...] = (
    FeeTier("Обычный", 0.00036, 0.0010),
    FeeTier("VIP 1", 0.00033, 0.00073),
    FeeTier("VIP 2", 0.00029, 0.00068),
    FeeTier("VIP 3", 0.00025, 0.00064),
    FeeTier("VIP 4", 0.00012, 0.00030),
    FeeTier("VIP 5", 0.00010, 0.00030),
    FeeTier("Максимальный VIP", 0.0, 0.00028),
)

OPTIONS_FEES: tuple[FeeTier, ...] = (
    FeeTier("Обычный", 0.00020, 0.00030),
    FeeTier("VIP 1", 0.00015, 0.00020),
    FeeTier("VIP 2", 0.00015, 0.00020),
    FeeTier("VIP 3", 0.00015, 0.00020),
    FeeTier("VIP 4", 0.00015, 0.00018),
    FeeTier("VIP 5", 0.00010, 0.00015),
    FeeTier("Максимальный VIP", 0.00005, 0.00015),
)

FIAT_SPOT_FEES: tuple[FeeTier, ...] = (
    FeeTier("<100,000 USD", 0.0015, 0.0020),
    FeeTier("<275,000 USD", 0.0010, 0.0020),
    FeeTier("<550,000 USD", 0.0010, 0.0015),
    FeeTier(">=550,000 USD", 0.0010, 0.0012),
)

BORROW_RATES: tuple[BorrowRate, ...] = (
    BorrowRate("BTC", 0.0000004480, 300.0),
    BorrowRate("ETH", 0.0000024570, 2_000.0),
    BorrowRate("USDT", 0.0000042903, 8_000_000.0),
    BorrowRate("USDC", 0.0000040683, 3_500_000.0),
    BorrowRate("ACH", 0.0000178893, 2_000_000.0),
    BorrowRate("ADA", 0.0000072371, 2_440_800.0),
    BorrowRate("AERO", 0.0000085128, 20_000.0),
    BorrowRate("1INCH", 0.0000155018, 763_800.0),
    BorrowRate("2Z", 0.0000340983, 98_200.0),
    BorrowRate("A", 0.0000124276, 60_000.0),
    BorrowRate("GMT", 0.0000278605, 800_000.0),
)

VIP_REQUIREMENTS: dict[str, float] = {
    "spot_30d_volume_usd": 1_000_000.0,
    "futures_30d_volume_usd": 10_000_000.0,
    "options_30d_volume_usd": 5_000_000.0,
    "net_borrow_30d_usd": 50_000.0,
    "total_capital_usd": 100_000.0,
    "avg_capital_30d_usd": 100_000.0,
}


def fee_table() -> dict[str, list[dict[str, object]]]:
    """Return all known fee tables."""

    return {
        "spot": [_tier_to_dict(tier) for tier in SPOT_FEES],
        "futures": [_tier_to_dict(tier) for tier in FUTURES_FEES],
        "options": [_tier_to_dict(tier) for tier in OPTIONS_FEES],
        "fiat_spot": [_tier_to_dict(tier) for tier in FIAT_SPOT_FEES],
    }


def borrow_table() -> list[dict[str, object]]:
    """Return borrow rates sorted from cheapest to most expensive."""

    return [_borrow_to_dict(rate) for rate in sorted(BORROW_RATES, key=lambda item: item.hourly_rate)]


def select_fee_rate(product: str = "spot", liquidity: str = "taker", vip_level: str = "Обычный") -> float:
    """Select fee rate for a product/liquidity/VIP combination."""

    product_key = product.strip().lower().replace("-", "_")
    liquidity_key = liquidity.strip().lower()
    table = {
        "spot": SPOT_FEES,
        "futures": FUTURES_FEES,
        "options": OPTIONS_FEES,
        "fiat_spot": FIAT_SPOT_FEES,
    }.get(product_key, SPOT_FEES)
    tier = _find_tier(table, vip_level)
    return tier.maker if liquidity_key == "maker" else tier.taker


def estimate_trade_cost(
    *,
    notional: float,
    product: str = "spot",
    liquidity: str = "taker",
    vip_level: str = "Обычный",
    round_trip: bool = True,
) -> dict[str, object]:
    """Estimate trading commission and break-even move."""

    clean_notional = max(float(notional), 0.0)
    rate = select_fee_rate(product=product, liquidity=liquidity, vip_level=vip_level)
    one_side_fee = clean_notional * rate
    total_fee = one_side_fee * (2 if round_trip else 1)
    break_even_move_percent = rate * (2 if round_trip else 1) * 100
    return {
        "product": product,
        "liquidity": liquidity,
        "vip_level": vip_level,
        "notional": clean_notional,
        "fee_rate": rate,
        "one_side_fee": one_side_fee,
        "round_trip_fee": total_fee,
        "break_even_move_percent": break_even_move_percent,
    }


def estimate_borrow_cost(symbol: str, amount: float, hours: float = 24.0) -> dict[str, object]:
    """Estimate borrow cost using known hourly rates from the screenshots."""

    rate = _find_borrow(symbol)
    clean_amount = max(float(amount), 0.0)
    clean_hours = max(float(hours), 0.0)
    interest = clean_amount * rate.hourly_rate * clean_hours
    return {
        "symbol": rate.symbol,
        "amount": clean_amount,
        "hours": clean_hours,
        "hourly_rate": rate.hourly_rate,
        "estimated_interest": interest,
        "max_loan_amount": rate.max_loan_amount,
    }


def best_trade_venue(notional: float, vip_level: str = "Обычный") -> dict[str, object]:
    """Return the cheapest known Bybit product/liquidity option for a notional."""

    candidates = []
    for product in ("spot", "futures", "options", "fiat_spot"):
        for liquidity in ("maker", "taker"):
            candidates.append(estimate_trade_cost(notional=notional, product=product, liquidity=liquidity, vip_level=vip_level))
    best = min(candidates, key=lambda item: float(item["round_trip_fee"]))
    worst = max(candidates, key=lambda item: float(item["round_trip_fee"]))
    saving = float(worst["round_trip_fee"]) - float(best["round_trip_fee"])
    return {
        "best": best,
        "worst": worst,
        "estimated_saving_vs_worst": saving,
        "recommendation": _recommendation(best),
        "candidates": sorted(candidates, key=lambda item: float(item["round_trip_fee"])),
    }


def vip_progress(metrics: dict[str, Any] | None = None) -> dict[str, object]:
    """Estimate progress toward lower fee requirements."""

    data = metrics or {}
    items = []
    for key, required in VIP_REQUIREMENTS.items():
        current = max(float(data.get(key, 0.0) or 0.0), 0.0)
        progress = 0.0 if required <= 0 else min(current / required, 1.0)
        missing = max(required - current, 0.0)
        items.append({"metric": key, "current": current, "required": required, "progress": progress, "missing": missing})
    best_path = min(items, key=lambda item: float(item["missing"]))
    return {
        "requirements": items,
        "best_path": best_path,
        "message": "AI будет учитывать эти требования перед частой торговлей и искать путь к меньшим комиссиям.",
    }


def ai_cost_report(notional: float = 500.0, vip_level: str = "Обычный") -> dict[str, object]:
    """Return full cost intelligence summary for the AI layer."""

    venue = best_trade_venue(notional=notional, vip_level=vip_level)
    cheapest_borrows = borrow_table()[:5]
    expensive_borrows = borrow_table()[-3:]
    return {
        "source": "user_bybit_screenshots_seeded_model",
        "vip_level": vip_level,
        "notional": notional,
        "fees": fee_table(),
        "borrow_rates": borrow_table(),
        "cheapest_borrows": cheapest_borrows,
        "expensive_borrows": expensive_borrows,
        "best_trade_venue": venue,
        "vip_progress": vip_progress(),
        "rules": [
            "Prefer maker orders when execution risk is acceptable.",
            "Avoid trades whose expected move is below round-trip commission break-even.",
            "Count borrow interest as loss before calculating net PnL.",
            "Avoid expensive borrow symbols unless signal strength is high enough to cover interest and fees.",
            "Monitor VIP progress because lower tiers reduce break-even threshold.",
        ],
    }


def _tier_to_dict(tier: FeeTier) -> dict[str, object]:
    return {"level": tier.level, "maker": tier.maker, "taker": tier.taker}


def _borrow_to_dict(rate: BorrowRate) -> dict[str, object]:
    return {
        "symbol": rate.symbol,
        "hourly_rate": rate.hourly_rate,
        "max_loan_amount": rate.max_loan_amount,
        "current_loan_amount": rate.current_loan_amount,
        "utilization": rate.utilization,
    }


def _find_tier(table: tuple[FeeTier, ...], vip_level: str) -> FeeTier:
    normalized = vip_level.strip().lower()
    for tier in table:
        if tier.level.lower() == normalized:
            return tier
    return table[0]


def _find_borrow(symbol: str) -> BorrowRate:
    normalized = symbol.strip().upper()
    for rate in BORROW_RATES:
        if rate.symbol == normalized:
            return rate
    return BorrowRate(normalized or "UNKNOWN", 0.00001, 0.0)


def _recommendation(best: dict[str, object]) -> str:
    product = str(best["product"])
    liquidity = str(best["liquidity"])
    fee = float(best["round_trip_fee"])
    return f"Самый дешёвый вариант из известных: {product} / {liquidity}. Расчётная круговая комиссия: {fee:.4f} USDT."
