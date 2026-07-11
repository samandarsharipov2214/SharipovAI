from trading_candidate import validate_trading_candidate

NOW = 1_700_000_000_000


def candidate(**overrides):
    payload = {
        "candidate_id": "cand-001",
        "symbol": "BTC/USDT",
        "category": "spot",
        "side": "buy",
        "environment": "testnet",
        "market_timestamp_ms": NOW - 1_000,
        "received_timestamp_ms": NOW - 500,
        "reference_price": 60_000,
        "data_sources": ["bybit-public-ws"],
        "market_regime": "trend",
        "signal_evidence": ["momentum-confirmed"],
        "news_evidence": [],
        "portfolio_snapshot_id": "portfolio-001",
        "estimated_fees": 0.1,
        "estimated_slippage": 0.2,
        "risk_score": 20,
        "risk_blocks": [],
        "confidence": 80,
        "consensus": 85,
        "decision": "allow",
        "expires_at_ms": NOW + 5_000,
    }
    payload.update(overrides)
    return payload


def test_valid_testnet_candidate_is_normalized_and_allowed():
    result = validate_trading_candidate(candidate(), now_ms=NOW)
    data = result.to_dict()
    assert result.valid is True
    assert result.execution_allowed is True
    assert result.effective_decision == "ALLOW"
    assert data["candidate"]["symbol"] == "BTCUSDT"
    assert data["candidate"]["side"] == "Buy"
    assert data["candidate"]["data_sources"] == ["bybit-public-ws"]


def test_missing_fields_fail_closed():
    payload = candidate()
    payload.pop("portfolio_snapshot_id")
    result = validate_trading_candidate(payload, now_ms=NOW)
    assert result.valid is False
    assert result.execution_allowed is False
    assert result.effective_decision == "BLOCK"
    assert "portfolio_snapshot_id" in result.errors[0]


def test_unknown_fields_are_rejected():
    result = validate_trading_candidate(candidate(secret_override=True), now_ms=NOW)
    assert result.valid is False
    assert "unknown fields" in result.errors[0]


def test_stale_testnet_market_data_is_invalid():
    result = validate_trading_candidate(candidate(market_timestamp_ms=NOW - 6_000), now_ms=NOW)
    assert result.valid is False
    assert result.effective_decision == "BLOCK"
    assert any("stale" in error for error in result.errors)


def test_risk_blocks_override_allow_decision():
    result = validate_trading_candidate(candidate(risk_blocks=["daily loss limit reached"]), now_ms=NOW)
    assert result.valid is True
    assert result.execution_allowed is False
    assert result.effective_decision == "BLOCK"
    assert result.policy_blocks == ("daily loss limit reached",)


def test_low_confidence_or_consensus_blocks_allow():
    result = validate_trading_candidate(candidate(confidence=69, consensus=60), now_ms=NOW)
    assert result.valid is True
    assert result.execution_allowed is False
    assert "confidence below 70" in result.policy_blocks
    assert "consensus below 70" in result.policy_blocks


def test_mainnet_candidate_requires_separate_security_approval():
    result = validate_trading_candidate(
        candidate(environment="mainnet", expires_at_ms=NOW + 4_000),
        now_ms=NOW,
    )
    assert result.valid is True
    assert result.execution_allowed is False
    assert result.effective_decision == "BLOCK"
    assert any("Mainnet" in blocker for blocker in result.policy_blocks)


def test_wait_candidate_can_be_valid_without_execution():
    result = validate_trading_candidate(candidate(decision="WAIT"), now_ms=NOW)
    assert result.valid is True
    assert result.execution_allowed is False
    assert result.effective_decision == "WAIT"
    assert result.status == "blocked"
