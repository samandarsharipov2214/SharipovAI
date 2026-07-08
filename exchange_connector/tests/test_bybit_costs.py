"""Tests for Bybit cost intelligence seeded from user screenshots."""

from __future__ import annotations

import pytest

from exchange_connector import (
    ai_cost_report,
    best_trade_venue,
    borrow_table,
    estimate_borrow_cost,
    estimate_trade_cost,
    fee_table,
    select_fee_rate,
    vip_progress,
)


def test_fee_table_contains_spot_futures_options_and_fiat_spot() -> None:
    """Fee tables should include the Bybit screens provided by the user."""

    tables = fee_table()

    assert set(tables) == {"spot", "futures", "options", "fiat_spot"}
    assert tables["spot"][0]["maker"] == pytest.approx(0.0010)
    assert tables["spot"][0]["taker"] == pytest.approx(0.0018)
    assert tables["futures"][0]["maker"] == pytest.approx(0.00036)
    assert tables["futures"][0]["taker"] == pytest.approx(0.0010)
    assert tables["options"][0]["maker"] == pytest.approx(0.00020)
    assert tables["options"][0]["taker"] == pytest.approx(0.00030)


def test_select_fee_rate_by_product_and_liquidity() -> None:
    """AI should select the right maker/taker rate for a product."""

    assert select_fee_rate("spot", "taker", "Обычный") == pytest.approx(0.0018)
    assert select_fee_rate("futures", "maker", "Обычный") == pytest.approx(0.00036)
    assert select_fee_rate("options", "maker", "Максимальный VIP") == pytest.approx(0.00005)


def test_estimate_trade_cost_counts_round_trip_fee() -> None:
    """Trading cost must include entry and exit commission when round_trip=True."""

    estimate = estimate_trade_cost(notional=500, product="futures", liquidity="maker", vip_level="Обычный")

    assert estimate["one_side_fee"] == pytest.approx(0.18)
    assert estimate["round_trip_fee"] == pytest.approx(0.36)
    assert estimate["break_even_move_percent"] == pytest.approx(0.072)


def test_borrow_table_is_sorted_and_contains_major_assets() -> None:
    """Borrow rates should include BTC, ETH, USDT, and USDC from screenshots."""

    rates = borrow_table()
    symbols = {item["symbol"] for item in rates}

    assert {"BTC", "ETH", "USDT", "USDC"}.issubset(symbols)
    assert rates[0]["hourly_rate"] <= rates[-1]["hourly_rate"]


def test_estimate_borrow_cost_counts_hourly_interest() -> None:
    """Borrow interest must be counted as cost/loss."""

    estimate = estimate_borrow_cost("USDT", 500, 24)

    assert estimate["symbol"] == "USDT"
    assert estimate["estimated_interest"] == pytest.approx(500 * 0.0000042903 * 24)


def test_best_trade_venue_finds_cheapest_known_option() -> None:
    """AI should find the cheapest known conditions for a trade notional."""

    result = best_trade_venue(notional=500, vip_level="Обычный")

    assert result["best"]["round_trip_fee"] <= result["worst"]["round_trip_fee"]
    assert result["estimated_saving_vs_worst"] >= 0
    assert "recommendation" in result


def test_vip_progress_reports_missing_requirements() -> None:
    """AI should understand what is missing for better VIP conditions."""

    progress = vip_progress({"total_capital_usd": 50_000})

    assert progress["best_path"]["missing"] >= 0
    assert any(item["metric"] == "total_capital_usd" for item in progress["requirements"])


def test_ai_cost_report_contains_rules_for_ai() -> None:
    """Full AI cost report should include fees, borrow rates, venue, and rules."""

    report = ai_cost_report(notional=500)

    assert report["source"] == "user_bybit_screenshots_seeded_model"
    assert report["best_trade_venue"]["best"]["round_trip_fee"] >= 0
    assert report["cheapest_borrows"]
    assert any("borrow" in rule.lower() or "займ" in rule.lower() for rule in report["rules"])
