from __future__ import annotations

from fastapi.testclient import TestClient

from learning.policy_action_guard import guard_action, guard_batch
from learning.policy_guard_app import app


BLOCK_ADVICE = {"recommended_action": "block_action", "must_notify_owner": True}
MANUAL_ADVICE = {"recommended_action": "manual_review", "must_notify_owner": True}
CAUTION_ADVICE = {"recommended_action": "caution", "must_notify_owner": False}


def test_block_action_blocks_high_risk_trade() -> None:
    result = guard_action({"action_type": "crypto_trade", "actor": "paper_trading_bot", "topic": "crypto_regulation"}, BLOCK_ADVICE)

    assert result["decision"] == "block"
    assert result["allowed"] is False
    assert result["must_notify_owner"] is True
    assert result["reason"] == "policy_block_action"


def test_manual_review_pauses_high_risk_action() -> None:
    result = guard_action({"action_type": "withdrawal", "actor": "portfolio_engine", "topic": "aml_kyc"}, MANUAL_ADVICE)

    assert result["decision"] == "manual_review"
    assert result["allowed"] is False
    assert result["reason"] == "manual_review_required"


def test_caution_allows_but_marks_risk() -> None:
    result = guard_action({"action_type": "portfolio_rebalance", "actor": "portfolio_engine"}, CAUTION_ADVICE)

    assert result["decision"] == "caution"
    assert result["allowed"] is True
    assert result["reason"] == "policy_caution"


def test_safe_action_allowed_even_when_blocked() -> None:
    result = guard_action({"action_type": "read_dashboard", "actor": "general_controller"}, BLOCK_ADVICE)

    assert result["decision"] == "allow"
    assert result["allowed"] is True
    assert result["reason"] == "safe_action"


def test_batch_uses_strictest_decision() -> None:
    result = guard_batch(
        [
            {"action_type": "read_dashboard", "actor": "general_controller"},
            {"action_type": "crypto_trade", "actor": "market_agent"},
        ],
        BLOCK_ADVICE,
    )

    assert result["decision"] == "block"
    assert result["allowed"] is False


def test_policy_guard_api_with_explicit_advice() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/policy-guard/check",
        json={
            "latest_advice": BLOCK_ADVICE,
            "action": {"action_type": "crypto_trade", "actor": "market_agent", "topic": "crypto_regulation"},
        },
    )

    assert response.status_code == 200
    assert response.json()["decision"] == "block"


def test_policy_guard_batch_api() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/policy-guard/check-batch",
        json={
            "latest_advice": CAUTION_ADVICE,
            "actions": [
                {"action_type": "read_dashboard", "actor": "general_controller"},
                {"action_type": "trade", "actor": "market_agent"},
            ],
        },
    )

    assert response.status_code == 200
    assert response.json()["decision"] == "caution"
