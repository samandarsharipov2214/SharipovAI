from __future__ import annotations

from dataclasses import replace

from exchange_connector.preview_candidate_bridge import bind_preview_to_candidate
from trading_candidate import TradingDecision, TradingEnvironment

from test_preview_candidate_bridge_v2 import NOW, candidate, preview


def assert_block(item, cand=None, **kwargs):
    result = bind_preview_to_candidate(item, cand or candidate(item), now_ms=kwargs.pop("now_ms", NOW), **kwargs)
    assert result.valid is False
    assert result.decision is TradingDecision.BLOCK
    assert result.execution_allowed is False
    return result


def test_maximum_loss_is_recomputed():
    item = replace(preview(), maximum_loss=1.0, risk_reward_ratio=18.05936)
    result = assert_block(item)
    assert "preview maximum_loss is inconsistent" in result.errors


def test_reward_is_recomputed_from_take_profit():
    item = replace(preview(), take_profit=64_100.0)
    result = assert_block(item)
    assert "preview potential_reward is inconsistent" in result.errors


def test_risk_and_capital_gates_are_recomputed():
    risky = replace(preview(), risk_percent_of_equity=2.0, max_risk_percent=1.0)
    assert "preview exceeds max_risk_percent" in assert_block(risky).errors

    no_margin = replace(preview(), required_capital=0.0)
    assert "preview required_capital is inconsistent" in assert_block(no_margin).errors

    insufficient = replace(preview(), available_balance=100.0)
    assert "preview required_capital exceeds available_balance" in assert_block(insufficient).errors


def test_malformed_fee_returns_block_not_exception():
    item = replace(preview(), estimated_entry_fee="bad")
    result = assert_block(item, candidate(preview()))
    assert any("estimated_entry_fee" in error or "estimated fees" in error for error in result.errors)


def test_external_safety_flags_cannot_be_self_asserted():
    for field in ("funding_included", "liquidation_checked", "correlation_checked"):
        item = replace(preview(), **{field: True})
        assert "preview self-asserts external safety checks" in assert_block(item).errors


def test_deserialized_enum_strings_return_block():
    item = preview()
    cand = candidate(item)
    object.__setattr__(cand, "category", "linear")
    object.__setattr__(cand, "side", "Buy")
    result = assert_block(item, cand)
    assert any("candidate category" in error for error in result.errors)
    assert any("candidate side" in error for error in result.errors)


def test_string_mainnet_environment_cannot_bypass_security_approval():
    item = preview()
    cand = candidate(item)
    object.__setattr__(cand, "environment", "mainnet")
    result = assert_block(item, cand)
    assert "candidate environment must be a TradingEnvironment" in result.errors

    enum_mainnet = replace(candidate(item), environment=TradingEnvironment.MAINNET)
    result = assert_block(item, enum_mainnet)
    assert any("trusted Security Guard approval" in error for error in result.errors)


def test_nonfinite_timestamp_is_blocked():
    result = assert_block(preview(), now_ms=float("nan"))
    assert "now_ms must be a positive integer" in result.errors


def test_spot_preview_stays_unleveraged():
    item = replace(preview(), category="spot", leverage=2.0, required_capital=641.28064)
    cand = replace(candidate(item), category=type(candidate(item).category).SPOT)
    result = assert_block(item, cand)
    assert "spot preview requires leverage=1" in result.errors


def test_market_slippage_must_be_adverse():
    buy = replace(
        preview(),
        entry_price=63_936.0,
        notional=639.36,
        estimated_slippage=0.64,
        maximum_loss=10.0 + 0.64064 + 0.63,
        potential_reward=0.01 * (66_000 - 63_936) - 0.64064 - 0.66,
    )
    buy = replace(
        buy,
        risk_reward_ratio=buy.potential_reward / buy.maximum_loss,
        required_capital=buy.notional / 2 + buy.estimated_entry_fee,
    )
    result = assert_block(buy)
    assert "market buy preview must use adverse entry slippage" in result.errors
