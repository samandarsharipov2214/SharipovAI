from __future__ import annotations

from dataclasses import dataclass

from exchange_connector.preview_candidate_bridge import preview_digest, validate_preview_candidate


@dataclass
class FakeResult:
    valid: bool = True
    effective_decision: str = "ALLOW"

    def to_dict(self):
        return {
            "valid": self.valid,
            "effective_decision": self.effective_decision,
            "execution_allowed": self.valid and self.effective_decision == "ALLOW",
        }


def _preview():
    return {
        "symbol": "BTCUSDT",
        "side": "buy",
        "order_type": "limit",
        "quantity": 0.01,
        "entry_price": 60000.0,
        "notional": 600.0,
        "estimated_entry_fee": 0.6,
        "estimated_exit_fee": 0.58,
        "estimated_slippage": 0.0,
        "stop_loss": 58000.0,
        "take_profit": 65000.0,
        "maximum_loss": 21.18,
        "potential_reward": 50.0,
        "risk_reward_ratio": 2.36,
        "risk_percent_of_equity": 0.42,
        "leverage": 1.0,
        "margin_required": 600.0,
        "executed": False,
        "executable": False,
        "sends_order": False,
    }


def _candidate(preview):
    token = "preview_sha256:" + preview_digest(preview)
    return {
        "symbol": "BTCUSDT",
        "side": "Buy",
        "reference_price": 60000.0,
        "estimated_fees": 1.18,
        "estimated_slippage": 0.0,
        "signal_evidence": [token, "strategy:test"],
    }


def test_matching_preview_and_candidate_are_linked():
    preview = _preview()
    result = validate_preview_candidate(preview, _candidate(preview), validator=lambda payload, now_ms=None: FakeResult())

    assert result.linked is True
    assert result.status == "linked"
    assert result.execution_allowed is False
    assert result.blockers == ()


def test_missing_digest_blocks_candidate():
    preview = _preview()
    candidate = _candidate(preview)
    candidate["signal_evidence"] = ["strategy:test"]

    result = validate_preview_candidate(preview, candidate, validator=lambda payload, now_ms=None: FakeResult())

    assert result.linked is False
    assert "verified preview digest" in result.blockers[0]


def test_tampered_preview_breaks_binding():
    preview = _preview()
    candidate = _candidate(preview)
    preview["quantity"] = 0.02

    result = validate_preview_candidate(preview, candidate, validator=lambda payload, now_ms=None: FakeResult())

    assert result.linked is False


def test_mismatched_price_fees_and_side_are_blocked():
    preview = _preview()
    candidate = _candidate(preview)
    candidate.update({"side": "Sell", "reference_price": 61000.0, "estimated_fees": 2.0})

    result = validate_preview_candidate(preview, candidate, validator=lambda payload, now_ms=None: FakeResult())

    assert result.linked is False
    assert any("side" in item for item in result.blockers)
    assert any("reference price" in item for item in result.blockers)
    assert any("fees" in item for item in result.blockers)


def test_invalid_candidate_contract_is_blocked():
    preview = _preview()
    result = validate_preview_candidate(
        preview,
        _candidate(preview),
        validator=lambda payload, now_ms=None: FakeResult(valid=False, effective_decision="BLOCK"),
    )

    assert result.linked is False
    assert "trading candidate contract is invalid" in result.blockers
    assert "trading candidate effective decision is not ALLOW" in result.blockers


def test_preview_safety_flags_are_mandatory():
    preview = _preview()
    preview["executable"] = True

    try:
        preview_digest(preview)
    except ValueError as exc:
        assert "executable=false" in str(exc)
    else:
        raise AssertionError("unsafe preview must be rejected")
