"""Non-executing shadow dual-run contract for Architecture V2.

The current paper path remains authoritative. A V2 challenger may be evaluated on
the same immutable market/evidence snapshot, but shadow output cannot execute,
mutate paper state, or override the authoritative decision.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Decision(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    WAIT = "WAIT"


@dataclass(frozen=True, slots=True)
class ShadowInput:
    snapshot_id: str
    evidence_hash: str
    market_ts_ms: int

    def __post_init__(self) -> None:
        if not self.snapshot_id.strip() or not self.evidence_hash.strip():
            raise ValueError("snapshot_id and evidence_hash must not be empty")
        if self.market_ts_ms <= 0:
            raise ValueError("market_ts_ms must be positive")


@dataclass(frozen=True, slots=True)
class PathDecision:
    path: str
    decision: Decision
    reason: str
    snapshot_id: str
    evidence_hash: str
    execution_authority: bool

    def __post_init__(self) -> None:
        if not self.path.strip() or not self.reason.strip():
            raise ValueError("path and reason must not be empty")
        if not self.snapshot_id.strip() or not self.evidence_hash.strip():
            raise ValueError("decision must retain snapshot and evidence lineage")


@dataclass(frozen=True, slots=True)
class ShadowComparison:
    snapshot_id: str
    authoritative: PathDecision
    challenger: PathDecision
    same_evidence: bool
    decision_match: bool
    challenger_execution_authority: bool = False

    def __post_init__(self) -> None:
        if self.challenger_execution_authority:
            raise ValueError("shadow challenger cannot have execution authority")
        if not self.authoritative.execution_authority:
            raise ValueError("current paper path must remain authoritative during shadow")
        if self.challenger.execution_authority:
            raise ValueError("challenger decision must be non-executing")


def compare_shadow(*, shadow_input: ShadowInput, authoritative: PathDecision, challenger: PathDecision) -> ShadowComparison:
    """Compare both paths only when they consumed the same immutable input."""
    for decision in (authoritative, challenger):
        if decision.snapshot_id != shadow_input.snapshot_id:
            raise ValueError("both paths must use the exact shadow snapshot")
        if decision.evidence_hash != shadow_input.evidence_hash:
            raise ValueError("both paths must use the exact evidence set")

    if authoritative.path == challenger.path:
        raise ValueError("authoritative and challenger paths must be distinct")

    return ShadowComparison(
        snapshot_id=shadow_input.snapshot_id,
        authoritative=authoritative,
        challenger=challenger,
        same_evidence=True,
        decision_match=authoritative.decision is challenger.decision,
        challenger_execution_authority=False,
    )


__all__ = [
    "Decision",
    "PathDecision",
    "ShadowComparison",
    "ShadowInput",
    "compare_shadow",
]
