from __future__ import annotations

from dataclasses import replace

from trading_candidate import (
    MarketRegime,
    TradingCandidate,
    TradingCategory,
    TradingDecision,
    TradingEnvironment,
    TradingSide,
    TrustedSecurityApproval,
    validate_trading_candidate,
)

NOW = 1_800_000_000_000


def candidate(**changes):
    base = TradingCandidate(
        candidate_id="cand-001",
        symbol="BTCUSDT",
        category=TradingCategory.LINEAR,
        side=TradingSide.BUY,
        environment=TradingEnvironment.PAPER,
        market_timestamp_ms=NOW - 500,
        received_timestamp_ms=NOW - 400,
        reference_price=64_000.0,
        data_sources=("bybit_ws", "binance_rest", "okx_rest"),
        market_regime=MarketRegime.TREND,
        signal_evidence=("momentum-confirmed", "spread-safe"),
        news_evidence=(),
        news_assessment_id="news-assessment-001",
        portfolio_snapshot_id="portfolio-001",
        cost_snapshot_id="cost-001",
        estimated_fees=0.64,
        estimated_slippage=0.25,
        risk_score=20.0,
        risk_blocks=(),
        confidence=80.0,
        consensus=75.0,
        decision=TradingDecision.ALLOW,
        expires_at_ms=NOW + 2_000,
    )
    return replace(base, **changes)


def approval(**changes):
    base = TrustedSecurityApproval(
        approval_id="approval-001",
        candidate_id="cand-001",
        environment=TradingEnvironment.MAINNET,
        approved_by="security-guard",
        approved_at_ms=NOW - 1_000,
        expires_at_ms=NOW + 60_000,
        manual_confirmation=True,
        security_guard_approved=True,
        kill_switch_off=True,
    )
    return replace(base, **changes)


def test_valid_paper_candidate_is_allowed() -> None:
    result = validate_trading_candidate(candidate(), now_ms=NOW)
    assert result.valid is True
    assert result.decision is TradingDecision.ALLOW
    assert result.effective_min_confidence == 70
    assert result.effective_min_consensus == 70


def test_caller_cannot_lower_allow_thresholds() -> None:
    result = validate_trading_candidate(
        candidate(confidence=69, consensus=69),
        now_ms=NOW,
        min_confidence=0,
        min_consensus=0,
    )
    assert result.valid is False
    assert result.decision is TradingDecision.BLOCK
    assert result.effective_min_confidence == 70
    assert result.effective_min_consensus == 70


def test_confidence_consensus_and_risk_use_zero_to_one_hundred_scale() -> None:
    result = validate_trading_candidate(
        candidate(confidence=101, consensus=101, risk_score=101),
        now_ms=NOW,
    )
    assert result.valid is False
    assert "confidence must be between 0.0 and 100.0" in result.errors
    assert "consensus must be between 0.0 and 100.0" in result.errors
    assert "risk_score must be between 0.0 and 100.0" in result.errors


def test_stale_future_expired_and_long_lived_candidates_fail_closed() -> None:
    cases = [
        candidate(market_timestamp_ms=NOW - 6_000),
        candidate(market_timestamp_ms=NOW + 1_001, received_timestamp_ms=NOW + 1_001),
        candidate(expires_at_ms=NOW),
        candidate(expires_at_ms=NOW + 10_001),
    ]
    for item in cases:
        assert validate_trading_candidate(item, now_ms=NOW).decision is TradingDecision.BLOCK


def test_allow_requires_three_sources_and_complete_snapshots() -> None:
    result = validate_trading_candidate(
        candidate(
            data_sources=("bybit_ws", "binance_rest"),
            news_assessment_id="",
            portfolio_snapshot_id="",
            cost_snapshot_id="",
        ),
        now_ms=NOW,
    )
    assert result.valid is False
    assert "ALLOW requires at least three independent data sources" in result.errors
    assert "news_assessment_id is required" in result.errors
    assert "portfolio_snapshot_id is required" in result.errors
    assert "cost_snapshot_id is required" in result.errors


def test_risk_blocks_and_unsafe_regime_cannot_be_allowed() -> None:
    blocked = validate_trading_candidate(
        candidate(risk_blocks=("daily-loss-limit",)),
        now_ms=NOW,
    )
    assert blocked.decision is TradingDecision.BLOCK
    for regime in (MarketRegime.ILLIQUID, MarketRegime.UNKNOWN):
        assert validate_trading_candidate(candidate(market_regime=regime), now_ms=NOW).decision is TradingDecision.BLOCK


def test_mainnet_cannot_self_assert_security_approval() -> None:
    item = candidate(
        environment=TradingEnvironment.MAINNET,
        security_approval_id="approval-001",
    )
    without_external = validate_trading_candidate(item, now_ms=NOW)
    assert without_external.decision is TradingDecision.BLOCK
    assert "external trusted Security Guard approval" in without_external.errors[0]

    with_external = validate_trading_candidate(
        item,
        now_ms=NOW,
        trusted_security_approvals={"approval-001": approval()},
    )
    assert with_external.valid is True
    assert with_external.decision is TradingDecision.ALLOW


def test_invalid_external_security_approval_fails_closed() -> None:
    item = candidate(
        environment=TradingEnvironment.MAINNET,
        security_approval_id="approval-001",
    )
    invalid = [
        approval(candidate_id="other"),
        approval(expires_at_ms=NOW),
        approval(expires_at_ms=NOW + 301_000),
        approval(manual_confirmation=False),
        approval(security_guard_approved=False),
        approval(kill_switch_off=False),
    ]
    for trusted in invalid:
        result = validate_trading_candidate(
            item,
            now_ms=NOW,
            trusted_security_approvals={"approval-001": trusted},
        )
        assert result.decision is TradingDecision.BLOCK


def test_duplicate_and_non_finite_evidence_fails_closed() -> None:
    result = validate_trading_candidate(
        candidate(
            data_sources=("bybit_ws", "bybit_ws", "okx_rest"),
            signal_evidence=("same", "same"),
            estimated_slippage=float("nan"),
        ),
        now_ms=NOW,
    )
    assert result.decision is TradingDecision.BLOCK
    assert "data_sources must not contain duplicates" in result.errors
    assert "signal_evidence must not contain duplicates" in result.errors
    assert "estimated_slippage must be a non-negative finite number" in result.errors


def test_serialization_uses_api_string_values() -> None:
    payload = candidate().to_dict()
    assert payload["category"] == "linear"
    assert payload["side"] == "Buy"
    assert payload["environment"] == "paper"
    assert payload["decision"] == "ALLOW"
