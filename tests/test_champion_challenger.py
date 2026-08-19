import pytest

from trading_core.champion_challenger import (
    ChallengerVerdict,
    ChampionChallengerCriteria,
    ReplayCandidateEvidence,
    evaluate_challenger,
)
from trading_core.performance_statistics import PerformanceStatistics


MANIFEST = "a" * 64


def _stats(**overrides):
    values = {
        "closed_trade_count": 60,
        "expectancy": 1.0,
        "profit_factor": 1.4,
        "max_drawdown_percent": 8.0,
        "turnover_ratio": 2.0,
        "turnover_percent": 200.0,
        "bootstrap_mean_lower": 0.4,
        "bootstrap_mean_upper": 1.6,
        "confidence_level": 0.95,
        "familywise_confidence_level": 0.975,
        "tested_variants": 2,
        "positive_expectancy_supported": True,
        "sufficient_evidence": True,
    }
    values.update(overrides)
    return PerformanceStatistics(**values)


def _evidence(candidate_id, statistics, **overrides):
    values = {
        "candidate_id": candidate_id,
        "cohort_id": "v2-paper-cohort-001",
        "replay_manifest_sha256": MANIFEST,
        "event_count": 10_000,
        "statistics": statistics,
    }
    values.update(overrides)
    return ReplayCandidateEvidence(**values)


def _criteria(**overrides):
    values = {
        "minimum_closed_trades": 30,
        "maximum_drawdown_increase_percent_points": 1.0,
        "maximum_turnover_increase_ratio": 0.10,
    }
    values.update(overrides)
    return ChampionChallengerCriteria(**values)


def test_accepts_only_clear_non_degrading_challenger_on_same_replay_cohort():
    champion = _evidence("champion", _stats())
    challenger = _evidence(
        "challenger",
        _stats(
            expectancy=2.4,
            profit_factor=1.6,
            max_drawdown_percent=7.5,
            turnover_ratio=2.1,
            turnover_percent=210.0,
            bootstrap_mean_lower=1.8,
            bootstrap_mean_upper=3.0,
        ),
    )

    report = evaluate_challenger(champion, challenger, _criteria())

    assert report.verdict is ChallengerVerdict.ACCEPT_CHALLENGER
    assert report.reasons == ("all_preregistered_champion_challenger_gates_passed",)
    assert report.execution_authority is False


def test_keeps_champion_when_statistical_separation_is_missing():
    champion = _evidence("champion", _stats())
    challenger = _evidence(
        "challenger",
        _stats(
            expectancy=1.2,
            profit_factor=1.5,
            bootstrap_mean_lower=0.6,
            bootstrap_mean_upper=1.8,
        ),
    )

    report = evaluate_challenger(champion, challenger, _criteria())

    assert report.verdict is ChallengerVerdict.KEEP_CHAMPION
    assert "challenger_confidence_interval_not_above_champion" in report.reasons


def test_keeps_champion_on_profit_factor_drawdown_or_turnover_degradation():
    champion = _evidence("champion", _stats())
    challenger = _evidence(
        "challenger",
        _stats(
            expectancy=2.5,
            profit_factor=1.2,
            max_drawdown_percent=9.5,
            turnover_ratio=2.5,
            turnover_percent=250.0,
            bootstrap_mean_lower=1.8,
            bootstrap_mean_upper=3.1,
        ),
    )

    report = evaluate_challenger(champion, challenger, _criteria())

    assert report.verdict is ChallengerVerdict.KEEP_CHAMPION
    assert "challenger_profit_factor_degraded" in report.reasons
    assert "challenger_drawdown_degraded_beyond_preregistered_limit" in report.reasons
    assert "challenger_turnover_increased_beyond_preregistered_limit" in report.reasons


def test_insufficient_sample_does_not_promote_challenger():
    champion = _evidence("champion", _stats(closed_trade_count=29))
    challenger = _evidence("challenger", _stats(expectancy=3.0, bootstrap_mean_lower=2.0))

    report = evaluate_challenger(champion, challenger, _criteria())

    assert report.verdict is ChallengerVerdict.INSUFFICIENT_EVIDENCE
    assert report.execution_authority is False


def test_rejects_cross_cohort_or_different_manifest_comparisons():
    champion = _evidence("champion", _stats())
    other_cohort = _evidence("challenger", _stats(), cohort_id="legacy-26-trades")
    other_manifest = _evidence("challenger", _stats(), replay_manifest_sha256="b" * 64)

    with pytest.raises(ValueError, match="same replay cohort"):
        evaluate_challenger(champion, other_cohort, _criteria())
    with pytest.raises(ValueError, match="same replay manifest"):
        evaluate_challenger(champion, other_manifest, _criteria())


def test_thresholds_are_explicit_and_cannot_be_negative():
    with pytest.raises(ValueError, match="minimum_closed_trades"):
        _criteria(minimum_closed_trades=0)
    with pytest.raises(ValueError, match="maximum_drawdown_increase_percent_points"):
        _criteria(maximum_drawdown_increase_percent_points=-0.1)
    with pytest.raises(ValueError, match="maximum_turnover_increase_ratio"):
        _criteria(maximum_turnover_increase_ratio=-0.1)
