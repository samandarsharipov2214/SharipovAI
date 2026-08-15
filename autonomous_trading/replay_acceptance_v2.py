"""Offline replay/champion-vs-challenger acceptance for Architecture V2.

This module is deliberately non-executing. It compares a current paper champion
against a GC V2 challenger on identical immutable inputs and fails closed unless
the challenger proves positive net-after-cost performance, sufficient sample
size, no look-ahead, no safety regressions, and respected Risk/Security vetoes.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Iterable


class ReplayPath(StrEnum):
    CHAMPION = "champion"
    CHALLENGER = "challenger"


@dataclass(frozen=True, slots=True)
class ReplayTrade:
    path: ReplayPath
    snapshot_id: str
    evidence_hash: str
    decision_ts_ms: int
    evidence_max_ts_ms: int
    gross_pnl: Decimal
    fees: Decimal
    slippage_cost: Decimal
    turnover: Decimal
    risk_veto_required: bool = False
    risk_veto_respected: bool = True
    security_veto_required: bool = False
    security_veto_respected: bool = True
    execution_authority: bool = False

    def __post_init__(self) -> None:
        if not self.snapshot_id.strip() or not self.evidence_hash.strip():
            raise ValueError("snapshot_id and evidence_hash must not be empty")
        if self.decision_ts_ms <= 0 or self.evidence_max_ts_ms <= 0:
            raise ValueError("timestamps must be positive")
        if self.evidence_max_ts_ms > self.decision_ts_ms:
            raise ValueError("look-ahead evidence is forbidden")
        if self.fees < 0 or self.slippage_cost < 0 or self.turnover < 0:
            raise ValueError("costs and turnover must be non-negative")
        if self.path is ReplayPath.CHALLENGER and self.execution_authority:
            raise ValueError("replay challenger cannot have execution authority")

    @property
    def net_pnl(self) -> Decimal:
        return self.gross_pnl - self.fees - self.slippage_cost


@dataclass(frozen=True, slots=True)
class ReplayPair:
    champion: ReplayTrade
    challenger: ReplayTrade

    def __post_init__(self) -> None:
        if self.champion.path is not ReplayPath.CHAMPION:
            raise ValueError("champion trade must use champion path")
        if self.challenger.path is not ReplayPath.CHALLENGER:
            raise ValueError("challenger trade must use challenger path")
        if self.champion.snapshot_id != self.challenger.snapshot_id:
            raise ValueError("both paths must use the exact same snapshot")
        if self.champion.evidence_hash != self.challenger.evidence_hash:
            raise ValueError("both paths must use the exact same evidence")


@dataclass(frozen=True, slots=True)
class ReplayMetrics:
    samples: int
    gross_pnl: Decimal
    fees: Decimal
    slippage_cost: Decimal
    net_pnl: Decimal
    turnover: Decimal
    wins: int
    losses: int
    max_drawdown: Decimal


@dataclass(frozen=True, slots=True)
class AcceptancePolicy:
    min_samples: int = 30
    min_challenger_net_pnl: Decimal = Decimal("0")
    min_net_advantage: Decimal = Decimal("0")
    max_challenger_drawdown: Decimal | None = None
    require_risk_veto_evidence: bool = True
    require_security_veto_evidence: bool = True

    def __post_init__(self) -> None:
        if self.min_samples <= 0:
            raise ValueError("min_samples must be positive")
        if self.max_challenger_drawdown is not None and self.max_challenger_drawdown < 0:
            raise ValueError("max_challenger_drawdown must be non-negative")


@dataclass(frozen=True, slots=True)
class AcceptanceResult:
    accepted: bool
    champion: ReplayMetrics
    challenger: ReplayMetrics
    net_advantage: Decimal
    risk_veto_cases: int
    security_veto_cases: int
    safety_regressions: tuple[str, ...]
    rejection_reasons: tuple[str, ...]
    execution_authority: bool = False

    def __post_init__(self) -> None:
        if self.execution_authority:
            raise ValueError("acceptance harness cannot grant execution authority")


def _metrics(trades: Iterable[ReplayTrade]) -> ReplayMetrics:
    rows = list(trades)
    equity = Decimal("0")
    peak = Decimal("0")
    max_drawdown = Decimal("0")
    gross = Decimal("0")
    fees = Decimal("0")
    slippage = Decimal("0")
    turnover = Decimal("0")
    wins = 0
    losses = 0

    for trade in rows:
        gross += trade.gross_pnl
        fees += trade.fees
        slippage += trade.slippage_cost
        turnover += trade.turnover
        net = trade.net_pnl
        equity += net
        if net > 0:
            wins += 1
        elif net < 0:
            losses += 1
        peak = max(peak, equity)
        drawdown = peak - equity
        max_drawdown = max(max_drawdown, drawdown)

    return ReplayMetrics(
        samples=len(rows),
        gross_pnl=gross,
        fees=fees,
        slippage_cost=slippage,
        net_pnl=gross - fees - slippage,
        turnover=turnover,
        wins=wins,
        losses=losses,
        max_drawdown=max_drawdown,
    )


def evaluate_acceptance(*, pairs: Iterable[ReplayPair], policy: AcceptancePolicy) -> AcceptanceResult:
    """Evaluate challenger acceptance without mutating paper authority.

    The function is intentionally fail-closed. It proves only an offline
    acceptance result; it never grants runtime execution or paper authority.
    """
    rows = list(pairs)
    champion_rows = [row.champion for row in rows]
    challenger_rows = [row.challenger for row in rows]

    champion = _metrics(champion_rows)
    challenger = _metrics(challenger_rows)
    net_advantage = challenger.net_pnl - champion.net_pnl

    safety_regressions: list[str] = []
    risk_veto_cases = 0
    security_veto_cases = 0

    for row in rows:
        for trade in (row.champion, row.challenger):
            if trade.risk_veto_required:
                risk_veto_cases += 1
                if not trade.risk_veto_respected:
                    safety_regressions.append(f"risk_veto_not_respected:{trade.path}:{trade.snapshot_id}")
            if trade.security_veto_required:
                security_veto_cases += 1
                if not trade.security_veto_respected:
                    safety_regressions.append(f"security_veto_not_respected:{trade.path}:{trade.snapshot_id}")

    reasons: list[str] = []
    if challenger.samples < policy.min_samples:
        reasons.append("insufficient_samples")
    if challenger.net_pnl <= policy.min_challenger_net_pnl:
        reasons.append("challenger_net_after_cost_not_positive_enough")
    if net_advantage <= policy.min_net_advantage:
        reasons.append("challenger_does_not_beat_champion")
    if policy.max_challenger_drawdown is not None and challenger.max_drawdown > policy.max_challenger_drawdown:
        reasons.append("challenger_drawdown_exceeds_limit")
    if safety_regressions:
        reasons.append("safety_regression")
    if policy.require_risk_veto_evidence and risk_veto_cases == 0:
        reasons.append("missing_risk_veto_evidence")
    if policy.require_security_veto_evidence and security_veto_cases == 0:
        reasons.append("missing_security_veto_evidence")

    return AcceptanceResult(
        accepted=not reasons,
        champion=champion,
        challenger=challenger,
        net_advantage=net_advantage,
        risk_veto_cases=risk_veto_cases,
        security_veto_cases=security_veto_cases,
        safety_regressions=tuple(safety_regressions),
        rejection_reasons=tuple(reasons),
        execution_authority=False,
    )


__all__ = [
    "AcceptancePolicy",
    "AcceptanceResult",
    "ReplayMetrics",
    "ReplayPair",
    "ReplayPath",
    "ReplayTrade",
    "evaluate_acceptance",
]
