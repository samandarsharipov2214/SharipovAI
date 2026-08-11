from config.meta_ai_contract import evaluate_agent_payloads, record_realized_result
from meta_ai import MetaAI


def test_synthetic_payload_does_not_change_reputation() -> None:
    meta = MetaAI()
    payloads = [
        {
            "agent_id": "synthetic_simulator",
            "action": "BUY",
            "confidence": 99,
            "evidence_score": 99,
            "risk_score": 1,
            "evidence_class": "synthetic_simulation",
            "learning_eligible": False,
        },
        {
            "agent_id": "market_intelligence",
            "action": "BUY",
            "confidence": 80,
            "evidence_score": 90,
            "risk_score": 20,
        },
    ]

    record_realized_result(meta, payloads, realized_action="BUY", regime="bull")
    snapshot = meta.reputations_snapshot("bull")

    # Neither synthetic nor merely well-formed-but-unverified evidence may train
    # reputation. Learning requires an explicit verified provenance signal.
    assert "synthetic_simulator" not in snapshot
    assert "market_intelligence" not in snapshot
