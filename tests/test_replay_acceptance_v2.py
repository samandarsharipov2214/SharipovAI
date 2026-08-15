from decimal import Decimal

import pytest

from autonomous_trading.replay_acceptance_v2 import (
    AcceptancePolicy,
    ReplayPair,
    ReplayPath,
    ReplayTrade,
    evaluate_acceptance,
)


def _trade(
    *,
    path: ReplayPath,
    snapshot_id: str,
    gross: str,
    fees: str = "1",
    slippage: str = "1",
    turnover: str = "100",
    risk_required: bool = False,
    risk_respected: bool = True,
    security_required: bool = False,
    security_respected: bool = True,
) -> ReplayTrade:
    return ReplayTrade(
        path=path,
        snapshot_id=snapshot_id,
        evidence_hash=f"evidence-{snapshot_id}",
        decision_ts_ms=2_000,
        evidence_max_ts_ms=1_999,
        gross_pnl=Decimal(gross),
        fees=Decimal(fees),
        slippage_cost=Decimal(slippage),
        turnover=Decimal(turnover),
        risk_veto_required=risk_required,
        risk_veto_respected=risk_respected,
        security_veto_required=security_required,
        security_veto_respected=security_respected,
        execution_authority=False,
    )


def _pair(index: int, *, champion_gross: str, challenger_gross: str, veto_evidence: bool = False) -> ReplayPair:
    snapshot_id = f"s{index}"
    return ReplayPair(
        champion=_trade(
            path=ReplayPath.CHAMPION,
            snapshot_id=snapshot_id,
            gross=champion_gross,
            risk_required=veto_evidence,
            security_required=veto_evidence,
        ),
        challenger=_trade(
            path=ReplayPath.CHALLENGER,
            snapshot_id=snapshot_id,
            gross=challenger_gross,
            risk_required=veto_evidence,
            security_required=veto_evidence,
        ),
    )


def test_accepts_only_positive_net_after_cost_challenger_that_beats_champion() -> None:
    pairs = [_pair(i, champion_gross="3", challenger_gross="5", veto_evidence=i == 0) for i in range(30)]

    result = evaluate_acceptance(
        pairs=pairs,
        policy=AcceptancePolicy(min_samples=30, max_challenger_drawdown=Decimal("10")),
    )

    assert result.accepted is True
    assert result.champion.net_pnl == Decimal("30")
    assert result.challenger.net_pnl == Decimal("90")
    assert result.net_advantage == Decimal("60")
    assert result.challenger.fees == Decimal("30")
    assert result.challenger.slippage_cost == Decimal("30")
    assert result.challenger.turnover == Decimal("3000")
    assert result.challenger.wins == 30
    assert result.challenger.losses == 0
    assert result.risk_veto_cases == 2
    assert result.security_veto_cases == 2
    assert result.execution_authority is False


def test_rejects_insufficient_samples_even_when_profitable() -> None:
    result = evaluate_acceptance(
        pairs=[_pair(i, champion_gross="2", challenger_gross="10", veto_evidence=i == 0) for i in range(5)],
        policy=AcceptancePolicy(min_samples=30),
    )

    assert result.accepted is False
    assert "insufficient_samples" in result.rejection_reasons


def test_rejects_challenger_that_is_positive_but_does_not_beat_champion() -> None:
    result = evaluate_acceptance(
        pairs=[_pair(i, champion_gross="10", challenger_gross="5", veto_evidence=i == 0) for i in range(30)],
        policy=AcceptancePolicy(min_samples=30),
    )

    assert result.challenger.net_pnl > 0
    assert result.accepted is False
    assert "challenger_does_not_beat_champion" in result.rejection_reasons


def test_rejects_safety_regression_when_challenger_ignores_veto() -> None:
    pairs = [_pair(i, champion_gross="2", challenger_gross="8", veto_evidence=i == 0) for i in range(30)]
    bad = pairs[0]
    pairs[0] = ReplayPair(
        champion=bad.champion,
        challenger=_trade(
            path=ReplayPath.CHALLENGER,
            snapshot_id="s0",
            gross="8",
            risk_required=True,
            risk_respected=False,
            security_required=True,
            security_respected=True,
        ),
    )

    result = evaluate_acceptance(pairs=pairs, policy=AcceptancePolicy(min_samples=30))

    assert result.accepted is False
    assert "safety_regression" in result.rejection_reasons
    assert any(item.startswith("risk_veto_not_respected:challenger:s0") for item in result.safety_regressions)


def test_rejects_when_no_veto_evidence_exists() -> None:
    result = evaluate_acceptance(
        pairs=[_pair(i, champion_gross="2", challenger_gross="8") for i in range(30)],
        policy=AcceptancePolicy(min_samples=30),
    )

    assert result.accepted is False
    assert "missing_risk_veto_evidence" in result.rejection_reasons
    assert "missing_security_veto_evidence" in result.rejection_reasons


def test_pair_requires_identical_immutable_inputs() -> None:
    champion = _trade(path=ReplayPath.CHAMPION, snapshot_id="a", gross="3")
    challenger = _trade(path=ReplayPath.CHALLENGER, snapshot_id="b", gross="4")

    with pytest.raises(ValueError, match="exact same snapshot"):
        ReplayPair(champion=champion, challenger=challenger)


def test_trade_rejects_look_ahead_evidence() -> None:
    with pytest.raises(ValueError, match="look-ahead"):
        ReplayTrade(
            path=ReplayPath.CHALLENGER,
            snapshot_id="s",
            evidence_hash="e",
            decision_ts_ms=1_000,
            evidence_max_ts_ms=1_001,
            gross_pnl=Decimal("1"),
            fees=Decimal("0"),
            slippage_cost=Decimal("0"),
            turnover=Decimal("10"),
        )


def test_challenger_can_never_have_execution_authority() -> None:
    with pytest.raises(ValueError, match="cannot have execution authority"):
        ReplayTrade(
            path=ReplayPath.CHALLENGER,
            snapshot_id="s",
            evidence_hash="e",
            decision_ts_ms=1_000,
            evidence_max_ts_ms=999,
            gross_pnl=Decimal("1"),
            fees=Decimal("0"),
            slippage_cost=Decimal("0"),
            turnover=Decimal("10"),
            execution_authority=True,
        )


def test_drawdown_limit_is_fail_closed() -> None:
    pairs = []
    for i in range(30):
        challenger_gross = "-8" if i == 10 else "8"
        pairs.append(_pair(i, champion_gross="2", challenger_gross=challenger_gross, veto_evidence=i == 0))

    result = evaluate_acceptance(
        pairs=pairs,
        policy=AcceptancePolicy(min_samples=30, max_challenger_drawdown=Decimal("5")),
    )

    assert result.challenger.net_pnl > 0
    assert result.challenger.max_drawdown > Decimal("5")
    assert result.accepted is False
    assert "challenger_drawdown_exceeds_limit" in result.rejection_reasons
