"""Fail-closed replay/shadow acceptance gate for Architecture V2.

This module has no execution authority. It evaluates evidence produced by replay and
shadow runs and can only return whether a challenger is eligible for a later,
separately-approved paper-authority promotion.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from typing import Iterable


class AcceptanceVerdict(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"


@dataclass(frozen=True, slots=True)
class AcceptanceThresholds:
    min_replay_samples: int = 200
    min_shadow_samples: int = 100
    min_decision_match_rate: float = 0.80
    max_risk_veto_miss_rate: float = 0.0
    max_security_veto_miss_rate: float = 0.0
    max_stale_evidence_trade_rate: float = 0.0
    max_sizing_violation_rate: float = 0.0
    max_settlement_error_rate: float = 0.0
    min_net_pnl_delta: float = 0.0
    max_drawdown_delta: float = 0.0

    def __post_init__(self) -> None:
        if self.min_replay_samples <= 0 or self.min_shadow_samples <= 0:
            raise ValueError("sample thresholds must be positive")
        for name in (
            "min_decision_match_rate",
            "max_risk_veto_miss_rate",
            "max_security_veto_miss_rate",
            "max_stale_evidence_trade_rate",
            "max_sizing_violation_rate",
            "max_settlement_error_rate",
        ):
            value = getattr(self, name)
            if not isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be finite and within [0, 1]")
        for name in ("min_net_pnl_delta", "max_drawdown_delta"):
            if not isfinite(getattr(self, name)):
                raise ValueError(f"{name} must be finite")


@dataclass(frozen=True, slots=True)
class AcceptanceEvidence:
    replay_samples: int
    shadow_samples: int
    decision_matches: int
    risk_veto_opportunities: int
    risk_veto_misses: int
    security_veto_opportunities: int
    security_veto_misses: int
    stale_evidence_opportunities: int
    stale_evidence_trades: int
    sizing_checks: int
    sizing_violations: int
    settlement_checks: int
    settlement_errors: int
    champion_net_pnl: float
    challenger_net_pnl: float
    champion_max_drawdown: float
    challenger_max_drawdown: float
    same_input_lineage: bool
    challenger_execution_authority: bool = False

    def __post_init__(self) -> None:
        count_fields = (
            "replay_samples",
            "shadow_samples",
            "decision_matches",
            "risk_veto_opportunities",
            "risk_veto_misses",
            "security_veto_opportunities",
            "security_veto_misses",
            "stale_evidence_opportunities",
            "stale_evidence_trades",
            "sizing_checks",
            "sizing_violations",
            "settlement_checks",
            "settlement_errors",
        )
        for name in count_fields:
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must not be negative")
        if self.decision_matches > self.shadow_samples:
            raise ValueError("decision_matches cannot exceed shadow_samples")
        pairs = (
            ("risk_veto_misses", "risk_veto_opportunities"),
            ("security_veto_misses", "security_veto_opportunities"),
            ("stale_evidence_trades", "stale_evidence_opportunities"),
            ("sizing_violations", "sizing_checks"),
            ("settlement_errors", "settlement_checks"),
        )
        for numerator, denominator in pairs:
            if getattr(self, numerator) > getattr(self, denominator):
                raise ValueError(f"{numerator} cannot exceed {denominator}")
        for name in (
            "champion_net_pnl",
            "challenger_net_pnl",
            "champion_max_drawdown",
            "challenger_max_drawdown",
        ):
            if not isfinite(getattr(self, name)):
                raise ValueError(f"{name} must be finite")
        if self.champion_max_drawdown < 0 or self.challenger_max_drawdown < 0:
            raise ValueError("drawdown values must be non-negative")
        if self.challenger_execution_authority:
            raise ValueError("acceptance challenger cannot have execution authority")


@dataclass(frozen=True, slots=True)
class AcceptanceCheck:
    name: str
    passed: bool
    actual: float | int | bool
    required: str


@dataclass(frozen=True, slots=True)
class AcceptanceReport:
    verdict: AcceptanceVerdict
    checks: tuple[AcceptanceCheck, ...]
    execution_authority: bool = False
    promotion_authority: bool = False

    def __post_init__(self) -> None:
        if self.execution_authority or self.promotion_authority:
            raise ValueError("acceptance report cannot execute or promote authority")
        expected = all(check.passed for check in self.checks)
        if (self.verdict is AcceptanceVerdict.PASS) != expected:
            raise ValueError("verdict must match all checks")

    @property
    def failed_checks(self) -> tuple[AcceptanceCheck, ...]:
        return tuple(check for check in self.checks if not check.passed)


def _rate(numerator: int, denominator: int) -> float:
    """Fail closed when a required opportunity/check category has no evidence."""
    if denominator <= 0:
        return 1.0
    return numerator / denominator


def evaluate_acceptance(
    evidence: AcceptanceEvidence,
    thresholds: AcceptanceThresholds | None = None,
) -> AcceptanceReport:
    """Evaluate challenger eligibility without granting any runtime authority."""
    t = thresholds or AcceptanceThresholds()

    decision_match_rate = _rate(evidence.decision_matches, evidence.shadow_samples)
    risk_veto_miss_rate = _rate(evidence.risk_veto_misses, evidence.risk_veto_opportunities)
    security_veto_miss_rate = _rate(
        evidence.security_veto_misses, evidence.security_veto_opportunities
    )
    stale_evidence_trade_rate = _rate(
        evidence.stale_evidence_trades, evidence.stale_evidence_opportunities
    )
    sizing_violation_rate = _rate(evidence.sizing_violations, evidence.sizing_checks)
    settlement_error_rate = _rate(evidence.settlement_errors, evidence.settlement_checks)
    net_pnl_delta = evidence.challenger_net_pnl - evidence.champion_net_pnl
    drawdown_delta = evidence.challenger_max_drawdown - evidence.champion_max_drawdown

    checks = (
        AcceptanceCheck("same_input_lineage", evidence.same_input_lineage, evidence.same_input_lineage, "true"),
        AcceptanceCheck("replay_samples", evidence.replay_samples >= t.min_replay_samples, evidence.replay_samples, f">={t.min_replay_samples}"),
        AcceptanceCheck("shadow_samples", evidence.shadow_samples >= t.min_shadow_samples, evidence.shadow_samples, f">={t.min_shadow_samples}"),
        AcceptanceCheck("decision_match_rate", decision_match_rate >= t.min_decision_match_rate, decision_match_rate, f">={t.min_decision_match_rate}"),
        AcceptanceCheck("risk_veto_miss_rate", risk_veto_miss_rate <= t.max_risk_veto_miss_rate, risk_veto_miss_rate, f"<={t.max_risk_veto_miss_rate}"),
        AcceptanceCheck("security_veto_miss_rate", security_veto_miss_rate <= t.max_security_veto_miss_rate, security_veto_miss_rate, f"<={t.max_security_veto_miss_rate}"),
        AcceptanceCheck("stale_evidence_trade_rate", stale_evidence_trade_rate <= t.max_stale_evidence_trade_rate, stale_evidence_trade_rate, f"<={t.max_stale_evidence_trade_rate}"),
        AcceptanceCheck("sizing_violation_rate", sizing_violation_rate <= t.max_sizing_violation_rate, sizing_violation_rate, f"<={t.max_sizing_violation_rate}"),
        AcceptanceCheck("settlement_error_rate", settlement_error_rate <= t.max_settlement_error_rate, settlement_error_rate, f"<={t.max_settlement_error_rate}"),
        AcceptanceCheck("net_pnl_delta", net_pnl_delta >= t.min_net_pnl_delta, net_pnl_delta, f">={t.min_net_pnl_delta}"),
        AcceptanceCheck("drawdown_delta", drawdown_delta <= t.max_drawdown_delta, drawdown_delta, f"<={t.max_drawdown_delta}"),
    )
    verdict = AcceptanceVerdict.PASS if all(check.passed for check in checks) else AcceptanceVerdict.FAIL
    return AcceptanceReport(verdict=verdict, checks=checks)


def failed_check_names(report: AcceptanceReport) -> tuple[str, ...]:
    return tuple(check.name for check in report.failed_checks)


__all__ = [
    "AcceptanceCheck",
    "AcceptanceEvidence",
    "AcceptanceReport",
    "AcceptanceThresholds",
    "AcceptanceVerdict",
    "evaluate_acceptance",
    "failed_check_names",
]
