import pytest

from autonomous_trading.shadow_dual_run_v2 import (
    Decision,
    PathDecision,
    ShadowInput,
    compare_shadow,
)


def _input() -> ShadowInput:
    return ShadowInput(snapshot_id="snap-1", evidence_hash="evidence-abc", market_ts_ms=1_786_814_000_000)


def _decision(path: str, decision: Decision, *, authority: bool) -> PathDecision:
    return PathDecision(
        path=path,
        decision=decision,
        reason="deterministic test decision",
        snapshot_id="snap-1",
        evidence_hash="evidence-abc",
        execution_authority=authority,
    )


def test_shadow_compares_same_snapshot_without_granting_challenger_authority() -> None:
    result = compare_shadow(
        shadow_input=_input(),
        authoritative=_decision("current-paper", Decision.BUY, authority=True),
        challenger=_decision("gc-v2-shadow", Decision.WAIT, authority=False),
    )
    assert result.same_evidence is True
    assert result.decision_match is False
    assert result.authoritative.execution_authority is True
    assert result.challenger_execution_authority is False
    assert result.challenger.execution_authority is False


def test_matching_decisions_are_recorded_without_promoting_challenger() -> None:
    result = compare_shadow(
        shadow_input=_input(),
        authoritative=_decision("current-paper", Decision.WAIT, authority=True),
        challenger=_decision("gc-v2-shadow", Decision.WAIT, authority=False),
    )
    assert result.decision_match is True
    assert result.challenger_execution_authority is False


def test_shadow_fails_closed_on_different_snapshot_or_evidence() -> None:
    wrong_snapshot = PathDecision(
        path="gc-v2-shadow",
        decision=Decision.WAIT,
        reason="different snapshot",
        snapshot_id="snap-2",
        evidence_hash="evidence-abc",
        execution_authority=False,
    )
    with pytest.raises(ValueError, match="exact shadow snapshot"):
        compare_shadow(
            shadow_input=_input(),
            authoritative=_decision("current-paper", Decision.WAIT, authority=True),
            challenger=wrong_snapshot,
        )

    wrong_evidence = PathDecision(
        path="gc-v2-shadow",
        decision=Decision.WAIT,
        reason="different evidence",
        snapshot_id="snap-1",
        evidence_hash="other-evidence",
        execution_authority=False,
    )
    with pytest.raises(ValueError, match="exact evidence set"):
        compare_shadow(
            shadow_input=_input(),
            authoritative=_decision("current-paper", Decision.WAIT, authority=True),
            challenger=wrong_evidence,
        )


def test_shadow_rejects_execution_authority_for_challenger() -> None:
    with pytest.raises(ValueError, match="challenger decision must be non-executing"):
        compare_shadow(
            shadow_input=_input(),
            authoritative=_decision("current-paper", Decision.WAIT, authority=True),
            challenger=_decision("gc-v2-shadow", Decision.BUY, authority=True),
        )


def test_shadow_requires_current_paper_authority() -> None:
    with pytest.raises(ValueError, match="current paper path must remain authoritative"):
        compare_shadow(
            shadow_input=_input(),
            authoritative=_decision("current-paper", Decision.WAIT, authority=False),
            challenger=_decision("gc-v2-shadow", Decision.WAIT, authority=False),
        )


def test_shadow_requires_distinct_paths() -> None:
    with pytest.raises(ValueError, match="must be distinct"):
        compare_shadow(
            shadow_input=_input(),
            authoritative=_decision("same-path", Decision.WAIT, authority=True),
            challenger=_decision("same-path", Decision.WAIT, authority=False),
        )
