"""Bridge Evidence Vault outcomes into Learning OS lessons."""

from __future__ import annotations

from typing import Any

from .evidence_vault import EvidenceVault
from .learning_memory import LearningMemory


def record_decision_outcome_and_learn(
    *,
    vault: EvidenceVault,
    memory: LearningMemory,
    decision_id: str,
    outcome: str,
    impact_score: float,
    notes: str = "",
    learning_signal: str = "neutral",
) -> dict[str, Any]:
    """Record outcome and create a lesson when the outcome is negative."""

    outcome_result = vault.add_outcome(
        decision_id=decision_id,
        outcome=outcome,
        impact_score=impact_score,
        notes=notes,
        learning_signal=learning_signal,
    )
    if outcome_result.get("status") != "ok":
        return outcome_result

    replay = vault.replay_decision(decision_id)
    lesson = None
    if impact_score < 0 or learning_signal in {"negative", "bad", "contradicted"}:
        decision = replay.get("decision", {})
        lesson = memory.record_mistake(
            bot=str(decision.get("actor", "learning_engine")),
            domain=str(decision.get("topic", "general")),
            mistake=f"Decision {decision.get('decision')} had negative outcome: {outcome}",
            consequence=notes or "negative impact recorded in Evidence Vault",
            source=f"evidence_vault:{decision_id}",
        )
    return {"status": "ok", "outcome": outcome_result, "replay": replay, "lesson": lesson}


def evidence_learning_snapshot(vault: EvidenceVault, memory: LearningMemory) -> dict[str, Any]:
    """Return combined evidence + learning snapshot."""

    return {
        "status": "ok",
        "evidence": vault.snapshot(),
        "learning": memory.snapshot(),
        "source_reputation": vault.source_reputation(),
    }
