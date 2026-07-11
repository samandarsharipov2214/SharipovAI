from __future__ import annotations

from dataclasses import replace

from exchange_connector.order_preview import OrderPreview
from exchange_connector.preview_candidate_bridge import bind_preview_to_candidate, preview_digest
from trading_candidate import (
    MarketRegime,
    TradingCandidate,
    TradingCategory,
    TradingDecision,
    TradingEnvironment,
    TradingSide,
)


def preview() -> OrderPreview:
    maximum_loss = 11 + 0.101 + 0.09
    reward = 19 - 0.101 - 0.12
    return OrderPreview(
        symbol="BTCUSDT", category="spot", side="buy", order_type="market",
        quantity=1.0, reference_price=100.0, entry_price=101.0,
        notional=101.0, estimated_entry_fee=0.101,
        estimated_exit_fee_at_stop=0.09, estimated_slippage=1.0,
        stop_loss=90.0, take_profit=120.0,
        maximum_loss=maximum_loss, potential_reward=reward,
        risk_reward_ratio=reward / maximum_loss,
        risk_percent_of_equity=maximum_loss / 10,
        max_risk_percent=5.0, leverage=1.0,
        required_capital=101.101, available_balance=200.0,
        instrument_rules_fetched_at_ms=1_000,
    )


def candidate(value: OrderPreview, *, token: str | None = None, confidence: float = 80.0, environment=TradingEnvironment.TESTNET) -> TradingCandidate:
    evidence = token if token is not None else f"preview_sha256:{preview_digest(value)}"
    return TradingCandidate(
        candidate_id="candidate-1", symbol="BTCUSDT", category=TradingCategory.SPOT,
        side=TradingSide.BUY, environment=environment,
        market_timestamp_ms=1_900, received_timestamp_ms=1_950,
        reference_price=100.0, data_sources=("bybit", "binance", "okx"),
        market_regime=MarketRegime.TREND, signal_evidence=(evidence,),
        news_evidence=(), news_assessment_id="news-1",
        portfolio_snapshot_id="portfolio-1", cost_snapshot_id="cost-1",
        estimated_fees=0.191, estimated_slippage=1.0,
        risk_score=20.0, risk_blocks=(), confidence=confidence, consensus=80.0,
        decision=TradingDecision.ALLOW, expires_at_ms=5_000,
    )


def test_valid_binding_never_allows_execution() -> None:
    value = preview()
    result = bind_preview_to_candidate(value, candidate(value), now_ms=2_000)
    assert result.valid is True
    assert result.decision is TradingDecision.ALLOW
    assert result.execution_allowed is False


def test_missing_wrong_or_multiple_digest_blocks() -> None:
    value = preview()
    wrong = candidate(value, token="preview_sha256:" + "0" * 64)
    assert bind_preview_to_candidate(value, wrong, now_ms=2_000).valid is False
    multiple = replace(candidate(value), signal_evidence=(
        f"preview_sha256:{preview_digest(value)}",
        f"preview_sha256:{preview_digest(value)}",
    ))
    assert bind_preview_to_candidate(value, multiple, now_ms=2_000).decision is TradingDecision.BLOCK


def test_tampered_derived_values_block() -> None:
    value = preview()
    for tampered in (
        replace(value, notional=99),
        replace(value, maximum_loss=1),
        replace(value, potential_reward=100),
        replace(value, risk_reward_ratio=99),
        replace(value, required_capital=1),
        replace(value, estimated_slippage=0),
    ):
        result = bind_preview_to_candidate(tampered, candidate(tampered), now_ms=2_000)
        assert result.valid is False


def test_identity_cost_and_canonical_candidate_mismatch_block() -> None:
    value = preview()
    assert bind_preview_to_candidate(value, replace(candidate(value), symbol="ETHUSDT"), now_ms=2_000).valid is False
    assert bind_preview_to_candidate(value, replace(candidate(value), estimated_fees=0), now_ms=2_000).valid is False
    assert bind_preview_to_candidate(value, candidate(value, confidence=10), now_ms=2_000).valid is False


def test_stale_future_and_nonfinite_preview_block() -> None:
    value = preview()
    assert bind_preview_to_candidate(value, candidate(value), now_ms=400_001, max_instrument_age_ms=999_999).valid is False
    future = replace(value, instrument_rules_fetched_at_ms=5_000)
    assert bind_preview_to_candidate(future, candidate(future), now_ms=2_000).valid is False
    nonfinite = replace(value, entry_price=float("nan"))
    assert bind_preview_to_candidate(nonfinite, candidate(nonfinite, token="preview_sha256:" + "0" * 64), now_ms=2_000).valid is False


def test_forbidden_flags_and_favorable_market_slippage_block() -> None:
    value = preview()
    assert bind_preview_to_candidate(replace(value, executable=True), candidate(replace(value, executable=True)), now_ms=2_000).valid is False
    asserted = replace(value, funding_included=True)
    assert bind_preview_to_candidate(asserted, candidate(asserted), now_ms=2_000).valid is False
    favorable = replace(value, entry_price=99.0, notional=99.0, estimated_entry_fee=0.099, estimated_slippage=1.0, required_capital=99.099)
    assert bind_preview_to_candidate(favorable, candidate(favorable), now_ms=2_000).valid is False


def test_mainnet_without_external_security_approval_blocks() -> None:
    value = preview()
    result = bind_preview_to_candidate(value, candidate(value, environment=TradingEnvironment.MAINNET), now_ms=2_000)
    assert result.decision is TradingDecision.BLOCK
    assert result.execution_allowed is False
