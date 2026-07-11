from __future__ import annotations

from dataclasses import replace

from exchange_connector.order_preview import OrderPreview
from exchange_connector.preview_candidate_bridge import bind_preview_to_candidate, evidence_token
from trading_candidate import (
    MarketRegime,
    TradingCandidate,
    TradingCategory,
    TradingDecision,
    TradingEnvironment,
    TradingSide,
)

NOW = 1_800_000_000_000


def preview() -> OrderPreview:
    return OrderPreview(
        symbol="BTCUSDT",
        category="linear",
        side="buy",
        order_type="market",
        quantity=0.01,
        reference_price=64_000.0,
        entry_price=64_064.0,
        notional=640.64,
        estimated_entry_fee=0.64064,
        estimated_exit_fee_at_stop=0.63,
        estimated_slippage=0.64,
        stop_loss=63_000.0,
        take_profit=66_000.0,
        maximum_loss=11.91064,
        potential_reward=18.04936,
        risk_reward_ratio=18.04936 / 11.91064,
        risk_percent_of_equity=0.119,
        max_risk_percent=1.0,
        leverage=2.0,
        required_capital=320.96064,
        available_balance=1000.0,
        instrument_rules_fetched_at_ms=NOW - 1_000,
    )


def candidate(item: OrderPreview | None = None, **changes) -> TradingCandidate:
    item = item or preview()
    base = TradingCandidate(
        candidate_id="candidate-001",
        symbol="BTCUSDT",
        category=TradingCategory.LINEAR,
        side=TradingSide.BUY,
        environment=TradingEnvironment.TESTNET,
        market_timestamp_ms=NOW - 500,
        received_timestamp_ms=NOW - 400,
        reference_price=item.reference_price,
        data_sources=("bybit_ws", "binance_rest", "okx_rest"),
        market_regime=MarketRegime.TREND,
        signal_evidence=(evidence_token(item), "momentum-confirmed"),
        news_evidence=(),
        news_assessment_id="news-001",
        portfolio_snapshot_id="portfolio-001",
        cost_snapshot_id="cost-001",
        estimated_fees=item.estimated_entry_fee + item.estimated_exit_fee_at_stop,
        estimated_slippage=item.estimated_slippage,
        risk_score=20.0,
        risk_blocks=(),
        confidence=85.0,
        consensus=80.0,
        decision=TradingDecision.ALLOW,
        expires_at_ms=NOW + 2_000,
    )
    return replace(base, **changes)


def test_valid_binding_is_allow_but_never_execution_permission():
    item = preview()
    result = bind_preview_to_candidate(item, candidate(item), now_ms=NOW)
    assert result.valid is True
    assert result.decision is TradingDecision.ALLOW
    assert result.execution_allowed is False
    assert result.to_dict()["execution_allowed"] is False


def test_missing_wrong_or_multiple_digest_tokens_block():
    item = preview()
    missing = candidate(item, signal_evidence=("momentum-confirmed",))
    assert bind_preview_to_candidate(item, missing, now_ms=NOW).valid is False
    wrong = candidate(item, signal_evidence=("preview_sha256:" + "0" * 64,))
    assert bind_preview_to_candidate(item, wrong, now_ms=NOW).valid is False
    multiple = candidate(item, signal_evidence=(evidence_token(item), "preview_sha256:" + "1" * 64))
    result = bind_preview_to_candidate(item, multiple, now_ms=NOW)
    assert result.valid is False
    assert any("exactly one" in error for error in result.errors)


def test_nonfinite_or_derived_field_tampering_blocks_without_exception():
    item = replace(preview(), quantity=float("nan"))
    result = bind_preview_to_candidate(item, candidate(preview()), now_ms=NOW)
    assert result.valid is False
    assert result.preview_digest == ""
    assert any("digest is invalid" in error for error in result.errors)

    inconsistent = replace(preview(), notional=999.0)
    result = bind_preview_to_candidate(inconsistent, candidate(inconsistent), now_ms=NOW)
    assert result.valid is False
    assert "preview notional is inconsistent" in result.errors

    bad_ratio = replace(preview(), risk_reward_ratio=99.0)
    result = bind_preview_to_candidate(bad_ratio, candidate(bad_ratio), now_ms=NOW)
    assert result.valid is False
    assert "preview risk_reward_ratio is inconsistent" in result.errors


def test_identity_and_cost_mismatches_block():
    item = preview()
    wrong = candidate(item, symbol="ETHUSDT", estimated_fees=99.0, estimated_slippage=99.0)
    result = bind_preview_to_candidate(item, wrong, now_ms=NOW)
    assert result.valid is False
    assert any("symbol mismatch" in error for error in result.errors)
    assert any("fees mismatch" in error for error in result.errors)
    assert any("slippage mismatch" in error for error in result.errors)


def test_preview_execution_flags_block():
    item = replace(preview(), executable=True)
    result = bind_preview_to_candidate(item, candidate(item), now_ms=NOW)
    assert result.valid is False
    assert "preview contains an execution or approval flag" in result.errors


def test_stale_future_and_unsafe_env_age_cap_block():
    stale = replace(preview(), instrument_rules_fetched_at_ms=NOW - 60_001)
    assert bind_preview_to_candidate(stale, candidate(stale), now_ms=NOW).valid is False
    future = replace(preview(), instrument_rules_fetched_at_ms=NOW + 1_001)
    assert bind_preview_to_candidate(future, candidate(future), now_ms=NOW).valid is False
    hard_cap = replace(preview(), instrument_rules_fetched_at_ms=NOW - 300_001)
    result = bind_preview_to_candidate(
        hard_cap,
        candidate(hard_cap),
        now_ms=NOW,
        max_instrument_rules_age_ms=999_999_999,
    )
    assert result.valid is False


def test_invalid_config_and_malformed_evidence_fail_closed():
    item = preview()
    malformed = candidate(item, signal_evidence=None)
    result = bind_preview_to_candidate(
        item, malformed, now_ms=NOW, max_instrument_rules_age_ms="invalid"
    )
    assert result.valid is False
    assert result.decision is TradingDecision.BLOCK
    assert any("signal_evidence" in error for error in result.errors)
    assert any("age_ms is invalid" in error for error in result.errors)


def test_candidate_validator_block_is_preserved():
    item = preview()
    unsafe = candidate(item, confidence=1.0)
    result = bind_preview_to_candidate(item, unsafe, now_ms=NOW)
    assert result.valid is False
    assert result.decision is TradingDecision.BLOCK
    assert any("candidate:" in error for error in result.errors)
