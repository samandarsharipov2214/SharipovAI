"""Fail-closed champion/challenger acceptance for PAPER/replay evaluation.

This module compares two already-computed ``PerformanceStatistics`` snapshots
from the same immutable replay cohort.  It is advisory only: an accepted
challenger is eligible for a later PAPER decision, never automatically promoted
or granted execution authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math
import re

from .performance_statistics import PerformanceStatistics

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ChallengerVerdict(StrEnum):
    ACCEPT_CHALLENGER = "ACCEPT_CHALLENGER"
    KEEP_CHAMPION = "KEEP_CHAMPION"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


@dataclass(frozen=True, slots=True)
class ReplayCandidateEvidence:
    candidate_id: str
    cohort_id: str
    replay_manifest_sha256: str
    event_count: int
    statistics: PerformanceStatistics

    def __post_init__(self) -> None:
        if not self.candidate_id.strip():
            raise ValueError("candidate_id is required")
        if not self.cohort_id.strip():
            raise ValueError("cohort_id is required")
        if not _SHA256.fullmatch(self.replay_manifest_sha256):
            raise ValueError("replay_manifest_sha256 must be 64 lowercase hex characters")
        if isinstance(self.event_count, bool) or not isinstance(self.event_count, int) or self.event_count <= 0:
            raise ValueError("event_count must be a positive integer")
        if self.statistics.execution_authority:
            raise ValueError("performance evidence must not have execution authority")


@dataclass(frozen=True, slots=True)
class ChampionChallengerCriteria:
    """Pre-registered non-degradation and improvement requirements."""

    minimum_closed_trades: int
    maximum_drawdown_increase_percent_points: float
    maximum_turnover_increase_ratio: float
    require_positive_expectancy_support: bool = True
    require_confidence_separation: bool = True

    def __post_init__(self) -> None:
        if (
            isinstance(self.minimum_closed_trades, bool)
            or not isinstance(self.minimum_closed_trades, int)
            or self.minimum_closed_trades <= 0
        ):
            raise ValueError("minimum_closed_trades must be a positive integer")
        for name, value in (
            ("maximum_drawdown_increase_percent_points", self.maximum_drawdown_increase_percent_points),
            ("maximum_turnover_increase_ratio", self.maximum_turnover_increase_ratio),
        ):
            if isinstance(value, bool) or not math.isfinite(float(value)) or float(value) < 0:
                raise ValueError(f"{name} must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class ChampionChallengerReport:
    champion_id: str
    challenger_id: str
    cohort_id: str
    replay_manifest_sha256: str
    event_count: int
    verdict: ChallengerVerdict
    reasons: tuple[str, ...]
    execution_authority: bool = False


def evaluate_challenger(
    champion: ReplayCandidateEvidence,
    challenger: ReplayCandidateEvidence,
    criteria: ChampionChallengerCriteria,
) -> ChampionChallengerReport:
    """Compare a challenger with the incumbent on exactly the same replay evidence."""

    _require_same_replay_cohort(champion, challenger)
    if champion.candidate_id == challenger.candidate_id:
        raise ValueError("champion and challenger must have different candidate_id values")

    champion_stats = champion.statistics
    challenger_stats = challenger.statistics
    if not champion_stats.sufficient_evidence or not challenger_stats.sufficient_evidence:
        return _report(
            champion,
            challenger,
            ChallengerVerdict.INSUFFICIENT_EVIDENCE,
            ("performance_statistics_marked_insufficient",),
        )
    if (
        champion_stats.closed_trade_count < criteria.minimum_closed_trades
        or challenger_stats.closed_trade_count < criteria.minimum_closed_trades
    ):
        return _report(
            champion,
            challenger,
            ChallengerVerdict.INSUFFICIENT_EVIDENCE,
            (
                "closed_trade_sample_below_preregistered_minimum",
                f"champion_observed={champion_stats.closed_trade_count}",
                f"challenger_observed={challenger_stats.closed_trade_count}",
                f"required={criteria.minimum_closed_trades}",
            ),
        )

    failures: list[str] = []
    if criteria.require_positive_expectancy_support and not challenger_stats.positive_expectancy_supported:
        failures.append("challenger_positive_expectancy_not_supported")
    if challenger_stats.expectancy <= champion_stats.expectancy:
        failures.append("challenger_expectancy_did_not_improve")
    if criteria.require_confidence_separation and (
        challenger_stats.bootstrap_mean_lower <= champion_stats.bootstrap_mean_upper
    ):
        failures.append("challenger_confidence_interval_not_above_champion")
    if challenger_stats.profit_factor < champion_stats.profit_factor:
        failures.append("challenger_profit_factor_degraded")
    if (
        challenger_stats.max_drawdown_percent
        > champion_stats.max_drawdown_percent + criteria.maximum_drawdown_increase_percent_points
    ):
        failures.append("challenger_drawdown_degraded_beyond_preregistered_limit")
    maximum_turnover = champion_stats.turnover_ratio * (1.0 + criteria.maximum_turnover_increase_ratio)
    if challenger_stats.turnover_ratio > maximum_turnover:
        failures.append("challenger_turnover_increased_beyond_preregistered_limit")

    if failures:
        return _report(
            champion,
            challenger,
            ChallengerVerdict.KEEP_CHAMPION,
            tuple(failures),
        )
    return _report(
        champion,
        challenger,
        ChallengerVerdict.ACCEPT_CHALLENGER,
        ("all_preregistered_champion_challenger_gates_passed",),
    )


def _require_same_replay_cohort(
    champion: ReplayCandidateEvidence,
    challenger: ReplayCandidateEvidence,
) -> None:
    if champion.cohort_id != challenger.cohort_id:
        raise ValueError("champion and challenger must use the same replay cohort")
    if champion.replay_manifest_sha256 != challenger.replay_manifest_sha256:
        raise ValueError("champion and challenger must use the same replay manifest")
    if champion.event_count != challenger.event_count:
        raise ValueError("champion and challenger must use the same replay event count")


def _report(
    champion: ReplayCandidateEvidence,
    challenger: ReplayCandidateEvidence,
    verdict: ChallengerVerdict,
    reasons: tuple[str, ...],
) -> ChampionChallengerReport:
    return ChampionChallengerReport(
        champion_id=champion.candidate_id,
        challenger_id=challenger.candidate_id,
        cohort_id=champion.cohort_id,
        replay_manifest_sha256=champion.replay_manifest_sha256,
        event_count=champion.event_count,
        verdict=verdict,
        reasons=reasons,
        execution_authority=False,
    )


__all__ = [
    "ChallengerVerdict",
    "ChampionChallengerCriteria",
    "ChampionChallengerReport",
    "ReplayCandidateEvidence",
    "evaluate_challenger",
]
