from meta_ai import MetaAI
from meta_ai_adapter import evaluate_agent_payloads, record_realized_result


def test_existing_payload_shape_is_supported():
    meta = MetaAI()
    payloads = [
        {"name": "Market AI", "decision": "BUY", "confidence": 0.8, "data_quality": 0.9, "risk": 0.2},
        {"name": "News AI", "decision": "BUY", "confidence": 0.7, "evidence_score": 0.8, "risk_score": 0.3},
    ]
    result = evaluate_agent_payloads(meta, payloads, regime="bull", min_agreement=0.5)
    assert result.action == "BUY"
    record_realized_result(meta, payloads, realized_action="BUY", regime="bull")
    snapshot = meta.reputations_snapshot("bull")
    assert snapshot["Market AI"]["total_predictions"] == 1
    assert snapshot["News AI"]["accuracy"] == 1.0
