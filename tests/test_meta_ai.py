from meta_ai import AgentOpinion, MetaAI, PredictionOutcome


def test_reputation_changes_by_regime_and_results():
    meta = MetaAI()
    meta.record_outcomes([
        PredictionOutcome("news", "BUY", "BUY", 0.8, 40, 2, "bull"),
        PredictionOutcome("news", "BUY", "SELL", 0.9, -20, 15, "bear"),
        PredictionOutcome("technical", "SELL", "SELL", 0.7, 30, 3, "bear"),
    ])
    snapshot = meta.reputations_snapshot("bear")
    assert snapshot["technical"]["current_weight"] > snapshot["news"]["current_weight"]


def test_dynamic_consensus_respects_reputation_and_gates():
    meta = MetaAI()
    meta.record_outcomes([
        PredictionOutcome("technical", "BUY", "BUY", 0.8, 20, 1, "bull") for _ in range(30)
    ])
    result = meta.dynamic_consensus([
        AgentOpinion("technical", "BUY", 0.8, 0.9, 0.2, "bull"),
        AgentOpinion("news", "SELL", 0.6, 0.6, 0.3, "bull"),
    ], regime="bull", min_agreement=0.5)
    assert result.action == "BUY"
    blocked = meta.dynamic_consensus([
        AgentOpinion("risk", "BLOCK", 1.0, 1.0, 1.0, "bull")
    ], regime="bull")
    assert blocked.action == "BLOCK" and blocked.blocked


def test_audit_and_optimizer_never_auto_remove_agents():
    meta = MetaAI()
    bad = [PredictionOutcome("weak", "BUY", "SELL", 0.95, -5, 12, "bear") for _ in range(25)]
    meta.record_outcomes(bad)
    audit = meta.audit_decision([
        AgentOpinion("weak", "BUY", 0.95),
        AgentOpinion("risk", "WAIT", 0.7),
    ], selected_action="BUY", realized_action="SELL")
    assert "weak" in audit.losing_agents
    recommendations = meta.optimizer_recommendations(similarity={("weak", "clone"): 0.95})
    assert recommendations
    assert all(not item.automatic_action_allowed for item in recommendations)


def test_no_opinions_defaults_to_wait():
    result = MetaAI().dynamic_consensus([])
    assert result.action == "WAIT"
    assert result.blocked
