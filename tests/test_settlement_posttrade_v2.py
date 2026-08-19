from decimal import Decimal

import pytest

from autonomous_trading.general_controller_v2 import TradingIntent
from autonomous_trading.settlement_posttrade_v2 import (
    CounterfactualAttribution,
    DecisionLineage,
    PositionSide,
    ReviewOutcome,
    SettlementFill,
    build_review,
)


def _lineage(intent: TradingIntent) -> DecisionLineage:
    return DecisionLineage(
        decision_id="decision-1",
        candidate_id="candidate-1",
        final_intent=intent,
        contributing_agents=("market_analysis", "news_analysis"),
        gate_verdicts=(("portfolio_engine", "PASS"), ("risk_engine", "PASS"), ("security_guard", "PASS")),
        evidence_ids=("ev-market", "ev-risk", "ev-security"),
    )


def test_long_settlement_preserves_side_and_cost_adjusted_pnl() -> None:
    fill = SettlementFill(
        side=PositionSide.LONG,
        quantity=Decimal("2"),
        entry_price=Decimal("100"),
        exit_price=Decimal("110"),
        entry_fee=Decimal("1"),
        exit_fee=Decimal("1"),
        realized_slippage_cost=Decimal("0.5"),
        opened_at_ms=1000,
        closed_at_ms=2000,
        entry_order_id="entry-1",
        exit_order_id="exit-1",
    )
    review = build_review(
        settlement_id="settlement-1",
        symbol="btcusdt",
        fill=fill,
        lineage=_lineage(TradingIntent.BUY),
        max_drawdown_quote=Decimal("4"),
    )

    assert review.fill.side is PositionSide.LONG
    assert review.fill.gross_pnl == Decimal("20")
    assert review.fill.fees == Decimal("2")
    assert review.fill.net_pnl == Decimal("17.5")
    assert review.outcome is ReviewOutcome.PROFIT
    assert review.to_dict()["lineage"]["final_intent"] == "BUY"
    assert review.to_dict()["lineage"]["entry_intent"] == "BUY"
    assert review.to_dict()["lineage"]["exit_intent"] is None
    assert review.to_dict()["execution_authority"] is False


def test_short_profit_does_not_get_relabelled_buy() -> None:
    fill = SettlementFill(
        side=PositionSide.SHORT,
        quantity=Decimal("3"),
        entry_price=Decimal("50"),
        exit_price=Decimal("45"),
        entry_fee=Decimal("0.5"),
        exit_fee=Decimal("0.5"),
        realized_slippage_cost=Decimal("1"),
        opened_at_ms=1000,
        closed_at_ms=2000,
        entry_order_id="entry-short",
        exit_order_id="exit-short",
    )
    review = build_review(
        settlement_id="settlement-short",
        symbol="ETHUSDT",
        fill=fill,
        lineage=_lineage(TradingIntent.SELL),
    )

    assert review.fill.gross_pnl == Decimal("15")
    assert review.fill.net_pnl == Decimal("13")
    assert review.outcome is ReviewOutcome.PROFIT
    assert review.lineage.final_intent is TradingIntent.SELL
    assert review.to_dict()["lineage"]["final_intent"] == "SELL"


def test_loss_does_not_change_original_direction() -> None:
    fill = SettlementFill(
        side=PositionSide.LONG,
        quantity=Decimal("1"),
        entry_price=Decimal("100"),
        exit_price=Decimal("95"),
        entry_fee=Decimal("0"),
        exit_fee=Decimal("0"),
        realized_slippage_cost=Decimal("0"),
        opened_at_ms=1000,
        closed_at_ms=2000,
        entry_order_id="entry-loss",
        exit_order_id="exit-loss",
    )
    review = build_review(
        settlement_id="settlement-loss",
        symbol="BTCUSDT",
        fill=fill,
        lineage=_lineage(TradingIntent.BUY),
    )

    assert review.outcome is ReviewOutcome.LOSS
    assert review.lineage.final_intent is TradingIntent.BUY


def test_losing_long_preserves_buy_entry_and_sell_exit_separately_from_outcome() -> None:
    fill = SettlementFill(
        side=PositionSide.LONG,
        quantity=Decimal("1"),
        entry_price=Decimal("100"),
        exit_price=Decimal("95"),
        entry_fee=Decimal("0.1"),
        exit_fee=Decimal("0.1"),
        realized_slippage_cost=Decimal("0.2"),
        opened_at_ms=1000,
        closed_at_ms=2000,
        entry_order_id="entry-long",
        exit_order_id="exit-long",
    )
    lineage = DecisionLineage(
        decision_id="entry-decision",
        candidate_id="entry-candidate",
        final_intent=TradingIntent.BUY,
        contributing_agents=("technical_analyst", "news_intelligence"),
        gate_verdicts=(("portfolio_engine", "PASS"), ("risk_engine", "PASS"), ("security_guard", "PASS")),
        evidence_ids=("entry-market", "entry-news"),
        exit_decision_id="exit-decision",
        exit_intent=TradingIntent.SELL,
        exit_evidence_ids=("exit-market", "exit-risk"),
    )
    review = build_review(
        settlement_id="settlement-long-loss",
        symbol="BTCUSDT",
        fill=fill,
        lineage=lineage,
    )

    payload = review.to_dict()
    assert review.outcome is ReviewOutcome.LOSS
    assert review.lineage.entry_intent is TradingIntent.BUY
    assert review.lineage.exit_intent is TradingIntent.SELL
    assert payload["lineage"]["entry_intent"] == "BUY"
    assert payload["lineage"]["exit_intent"] == "SELL"
    assert payload["outcome"] == "LOSS"


def test_exit_lineage_is_atomic_and_must_close_the_position_side() -> None:
    with pytest.raises(ValueError, match="requires exit_decision_id, exit_intent and exit_evidence_ids together"):
        DecisionLineage(
            decision_id="entry-decision",
            candidate_id="entry-candidate",
            final_intent=TradingIntent.BUY,
            contributing_agents=("technical_analyst",),
            gate_verdicts=(("risk_engine", "PASS"),),
            evidence_ids=("entry-market",),
            exit_intent=TradingIntent.SELL,
        )

    fill = SettlementFill(
        side=PositionSide.LONG,
        quantity=Decimal("1"),
        entry_price=Decimal("100"),
        exit_price=Decimal("101"),
        entry_fee=Decimal("0"),
        exit_fee=Decimal("0"),
        realized_slippage_cost=Decimal("0"),
        opened_at_ms=1000,
        closed_at_ms=2000,
        entry_order_id="entry",
        exit_order_id="exit",
    )
    bad_exit = DecisionLineage(
        decision_id="entry-decision",
        candidate_id="entry-candidate",
        final_intent=TradingIntent.BUY,
        contributing_agents=("technical_analyst",),
        gate_verdicts=(("risk_engine", "PASS"),),
        evidence_ids=("entry-market",),
        exit_decision_id="exit-decision",
        exit_intent=TradingIntent.BUY,
        exit_evidence_ids=("exit-market",),
    )
    with pytest.raises(ValueError, match="exit_intent must close the actual opened position side"):
        build_review(
            settlement_id="settlement-bad-exit",
            symbol="BTCUSDT",
            fill=fill,
            lineage=bad_exit,
        )


def test_lineage_must_match_actual_position_side() -> None:
    fill = SettlementFill(
        side=PositionSide.SHORT,
        quantity=Decimal("1"),
        entry_price=Decimal("100"),
        exit_price=Decimal("90"),
        entry_fee=Decimal("0"),
        exit_fee=Decimal("0"),
        realized_slippage_cost=Decimal("0"),
        opened_at_ms=1000,
        closed_at_ms=2000,
        entry_order_id="entry",
        exit_order_id="exit",
    )

    with pytest.raises(ValueError, match="must match the actual opened position side"):
        build_review(
            settlement_id="settlement-mismatch",
            symbol="BTCUSDT",
            fill=fill,
            lineage=_lineage(TradingIntent.BUY),
        )


def test_wait_cannot_be_settled() -> None:
    with pytest.raises(ValueError, match="WAIT cannot settle"):
        _lineage(TradingIntent.WAIT)


def test_counterfactual_attribution_is_role_aware_and_non_mutating() -> None:
    attribution = CounterfactualAttribution(
        sizing_error=True,
        risk_error=True,
        controller_synthesis_error=True,
        notes=("size exceeded the best counterfactual",),
    )

    assert attribution.implicated_roles == (
        "portfolio_engine",
        "risk_engine",
        "general_controller",
    )


def test_negative_costs_and_drawdown_are_rejected() -> None:
    with pytest.raises(ValueError, match="entry_fee must be non-negative"):
        SettlementFill(
            side=PositionSide.LONG,
            quantity=Decimal("1"),
            entry_price=Decimal("100"),
            exit_price=Decimal("101"),
            entry_fee=Decimal("-1"),
            exit_fee=Decimal("0"),
            realized_slippage_cost=Decimal("0"),
            opened_at_ms=1000,
            closed_at_ms=2000,
            entry_order_id="entry",
            exit_order_id="exit",
        )

    fill = SettlementFill(
        side=PositionSide.LONG,
        quantity=Decimal("1"),
        entry_price=Decimal("100"),
        exit_price=Decimal("101"),
        entry_fee=Decimal("0"),
        exit_fee=Decimal("0"),
        realized_slippage_cost=Decimal("0"),
        opened_at_ms=1000,
        closed_at_ms=2000,
        entry_order_id="entry",
        exit_order_id="exit",
    )
    with pytest.raises(ValueError, match="max_drawdown_quote must be non-negative"):
        build_review(
            settlement_id="settlement-dd",
            symbol="BTCUSDT",
            fill=fill,
            lineage=_lineage(TradingIntent.BUY),
            max_drawdown_quote=Decimal("-0.1"),
        )
