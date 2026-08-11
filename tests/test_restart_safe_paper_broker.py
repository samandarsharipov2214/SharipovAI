from __future__ import annotations

import math

import pytest

from storage import ProjectDatabase
from trading_core.models import MarketEvent, Side
from trading_core.paper_broker import PaperBrokerConfig, RestartSafePaperBroker


def _event(
    timestamp_ms: int,
    *,
    bid: float = 99.0,
    ask: float = 101.0,
    funding_rate: float = 0.0,
) -> MarketEvent:
    return MarketEvent(
        timestamp_ms=timestamp_ms,
        symbol="BTCUSDT",
        bid=bid,
        ask=ask,
        source="verified-test-market",
        volume=1_000.0,
        funding_rate=funding_rate,
        funding_interval_hours=8.0,
    )


def _database(tmp_path) -> ProjectDatabase:
    return ProjectDatabase(f"sqlite:///{tmp_path / 'paper.db'}")


def test_paper_broker_fill_is_idempotent_across_restart(tmp_path) -> None:
    database = _database(tmp_path)
    broker = RestartSafePaperBroker(database=database, account_id="paper-a")
    event = _event(1_000)

    first = broker.execute(
        fill_id="fill-1",
        event=event,
        side=Side.BUY,
        quantity=1.0,
        reason="verified_candidate",
    )
    restarted = RestartSafePaperBroker(database=database, account_id="paper-a")
    duplicate = restarted.execute(
        fill_id="fill-1",
        event=event,
        side=Side.BUY,
        quantity=1.0,
        reason="verified_candidate",
    )

    assert first["duplicate"] is False
    assert duplicate["duplicate"] is True
    snapshot = restarted.snapshot({"BTCUSDT": event.mid})
    assert len(snapshot["fills"]) == 1
    assert snapshot["positions"]["BTCUSDT"]["quantity"] == 1.0
    assert snapshot["restart_safe"] is True


def test_paper_broker_rejects_oversell_without_mutating_position(tmp_path) -> None:
    broker = RestartSafePaperBroker(database=_database(tmp_path), account_id="paper-b")
    event = _event(1_000)
    broker.execute(
        fill_id="buy-1",
        event=event,
        side=Side.BUY,
        quantity=1.0,
        reason="verified_candidate",
    )

    with pytest.raises(RuntimeError, match="sell exceeds open position"):
        broker.execute(
            fill_id="sell-too-much",
            event=_event(2_000),
            side=Side.SELL,
            quantity=2.0,
            reason="risk_exit",
        )

    snapshot = broker.snapshot({"BTCUSDT": 100.0})
    assert snapshot["positions"]["BTCUSDT"]["quantity"] == 1.0
    assert len(snapshot["fills"]) == 1


def test_paper_broker_accrues_deterministic_funding_and_survives_restart(tmp_path) -> None:
    database = _database(tmp_path)
    broker = RestartSafePaperBroker(database=database, account_id="paper-c")
    broker.execute(
        fill_id="buy-1",
        event=_event(1_000, funding_rate=0.01),
        side=Side.BUY,
        quantity=1.0,
        reason="verified_candidate",
    )

    four_hours_ms = 4 * 60 * 60 * 1_000
    marked = broker.mark(_event(1_000 + four_hours_ms, funding_rate=0.01))
    assert marked["total_funding"] == pytest.approx(0.5)
    assert len(marked["funding_payments"]) == 1

    restarted = RestartSafePaperBroker(database=database, account_id="paper-c")
    restored = restarted.snapshot({"BTCUSDT": 100.0})
    assert restored["total_funding"] == pytest.approx(0.5)
    assert restored["positions"]["BTCUSDT"]["funding_paid"] == pytest.approx(0.5)


def test_paper_broker_rejects_non_finite_or_non_positive_quantity(tmp_path) -> None:
    broker = RestartSafePaperBroker(database=_database(tmp_path), account_id="paper-d")
    for quantity in (0.0, -1.0, math.nan, math.inf):
        with pytest.raises(ValueError, match="quantity must be positive and finite"):
            broker.execute(
                fill_id=f"invalid-{quantity}",
                event=_event(1_000),
                side=Side.BUY,
                quantity=quantity,
                reason="verified_candidate",
            )


def test_paper_broker_config_is_fail_closed() -> None:
    with pytest.raises(ValueError, match="initial_cash"):
        PaperBrokerConfig(initial_cash=float("nan"))
    with pytest.raises(ValueError, match="maximum_fills"):
        PaperBrokerConfig(maximum_fills=99)
