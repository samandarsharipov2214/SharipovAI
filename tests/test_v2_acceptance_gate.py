import math

import pytest

from autonomous_trading.v2_acceptance_gate import (
    AcceptanceEvidence,
    AcceptanceThresholds,
    AcceptanceVerdict,
    evaluate_acceptance,
    failed_check_names,
)


def passing_evidence(**overrides):
    values = dict(
        replay_samples=250,
        shadow_samples=120,
        decision_matches=110,
        risk_veto_opportunities=10,
        risk_veto_misses=0,
        security_veto_opportunities=8,
        security_veto_misses=0,
        stale_evidence_opportunities=7,
        stale_evidence_trades=0,
        sizing_checks=120,
        sizing_violations=0,
        settlement_checks=120,
        settlement_errors=0,
        champion_net_pnl=100.0,
        challenger_net_pnl=105.0,
        champion_max_drawdown=20.0,
        challenger_max_drawdown=19.0,
        same_input_lineage=True,
        challenger_execution_authority=False,
    )
    values.update(overrides)
    return AcceptanceEvidence(**values)


def test_passing_challenger_is_eligible_but_gets_no_authority():
    report = evaluate_acceptance(passing_evidence())

    assert report.verdict is AcceptanceVerdict.PASS
    assert report.failed_checks == ()
    assert report.execution_authority is False
    assert report.promotion_authority is False


def test_missing_input_lineage_fails_closed():
    report = evaluate_acceptance(passing_evidence(same_input_lineage=False))

    assert report.verdict is AcceptanceVerdict.FAIL
    assert "same_input_lineage" in failed_check_names(report)


@pytest.mark.parametrize(
    ("field", "value", "failed_check"),
    [
        ("replay_samples", 199, "replay_samples"),
        ("shadow_samples", 99, "shadow_samples"),
        ("decision_matches", 70, "decision_match_rate"),
        ("risk_veto_misses", 1, "risk_veto_miss_rate"),
        ("security_veto_misses", 1, "security_veto_miss_rate"),
        ("stale_evidence_trades", 1, "stale_evidence_trade_rate"),
        ("sizing_violations", 1, "sizing_violation_rate"),
        ("settlement_errors", 1, "settlement_error_rate"),
        ("challenger_net_pnl", 99.99, "net_pnl_delta"),
        ("challenger_max_drawdown", 20.01, "drawdown_delta"),
    ],
)
def test_each_acceptance_invariant_can_fail_independently(field, value, failed_check):
    report = evaluate_acceptance(passing_evidence(**{field: value}))

    assert report.verdict is AcceptanceVerdict.FAIL
    assert failed_check in failed_check_names(report)


def test_zero_required_evidence_categories_fail_closed():
    evidence = passing_evidence(
        risk_veto_opportunities=0,
        security_veto_opportunities=0,
        stale_evidence_opportunities=0,
        sizing_checks=0,
        settlement_checks=0,
    )

    report = evaluate_acceptance(evidence)

    assert report.verdict is AcceptanceVerdict.FAIL
    assert {
        "risk_veto_miss_rate",
        "security_veto_miss_rate",
        "stale_evidence_trade_rate",
        "sizing_violation_rate",
        "settlement_error_rate",
    }.issubset(set(failed_check_names(report)))


def test_custom_thresholds_are_respected():
    thresholds = AcceptanceThresholds(
        min_replay_samples=10,
        min_shadow_samples=10,
        min_decision_match_rate=0.5,
        max_risk_veto_miss_rate=0.1,
        max_security_veto_miss_rate=0.1,
        max_stale_evidence_trade_rate=0.1,
        max_sizing_violation_rate=0.1,
        max_settlement_error_rate=0.1,
        min_net_pnl_delta=-5.0,
        max_drawdown_delta=5.0,
    )
    evidence = passing_evidence(
        replay_samples=10,
        shadow_samples=10,
        decision_matches=5,
        risk_veto_opportunities=10,
        risk_veto_misses=1,
        security_veto_opportunities=10,
        security_veto_misses=1,
        stale_evidence_opportunities=10,
        stale_evidence_trades=1,
        sizing_checks=10,
        sizing_violations=1,
        settlement_checks=10,
        settlement_errors=1,
        challenger_net_pnl=95.0,
        challenger_max_drawdown=25.0,
    )

    assert evaluate_acceptance(evidence, thresholds).verdict is AcceptanceVerdict.PASS


def test_challenger_execution_authority_is_structurally_rejected():
    with pytest.raises(ValueError, match="cannot have execution authority"):
        passing_evidence(challenger_execution_authority=True)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("decision_matches", 121),
        ("risk_veto_misses", 11),
        ("security_veto_misses", 9),
        ("stale_evidence_trades", 8),
        ("sizing_violations", 121),
        ("settlement_errors", 121),
    ],
)
def test_invalid_count_relationships_are_rejected(field, value):
    with pytest.raises(ValueError):
        passing_evidence(**{field: value})


@pytest.mark.parametrize("field", ["replay_samples", "shadow_samples", "sizing_checks"])
def test_negative_counts_are_rejected(field):
    with pytest.raises(ValueError, match="must not be negative"):
        passing_evidence(**{field: -1})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("champion_net_pnl", math.nan),
        ("challenger_net_pnl", math.inf),
        ("champion_max_drawdown", math.nan),
        ("challenger_max_drawdown", math.inf),
    ],
)
def test_non_finite_performance_evidence_is_rejected(field, value):
    with pytest.raises(ValueError, match="must be finite"):
        passing_evidence(**{field: value})


def test_negative_drawdown_is_rejected():
    with pytest.raises(ValueError, match="drawdown values must be non-negative"):
        passing_evidence(challenger_max_drawdown=-0.01)


def test_thresholds_reject_invalid_rates_and_sample_counts():
    with pytest.raises(ValueError, match="sample thresholds must be positive"):
        AcceptanceThresholds(min_replay_samples=0)

    with pytest.raises(ValueError, match="within \[0, 1\]"):
        AcceptanceThresholds(min_decision_match_rate=1.01)

    with pytest.raises(ValueError, match="must be finite"):
        AcceptanceThresholds(max_drawdown_delta=math.inf)
