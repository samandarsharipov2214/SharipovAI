from __future__ import annotations

from pathlib import Path

import pytest

from exchange_connector.execution_kill_switch import PersistentExecutionKillSwitch
from storage import ProjectDatabase
from trading_core import (
    BacktestConfig,
    MarketEvent,
    RestartSafePaperBroker,
    Side,
    StrategySuiteConfig,
    evaluate_strategy_suite,
)
from validation import FillObservation, ShadowExecutionValidator


def _database(path: Path) -> ProjectDatabase:
    database = ProjectDatabase(f"sqlite:///{path}")
    database.initialize()
    return database


def test_persistent_kill_switch_survives_restart_and_clears_only_after_reconciliation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EXECUTION_KILL_SWITCH", "0")
    database = _database(tmp_path / "kill-switch.db")

    first = PersistentExecutionKillSwitch(database)
    assert first.state().active is False
    tripped = first.trip(reason="ambiguous_timeout", actor="test")
    assert tripped.active is True

    restarted = PersistentExecutionKillSwitch(_database(tmp_path / "kill-switch.db"))
    assert restarted.state().active is True
    with pytest.raises(RuntimeError, match="restart-safe reconciliation"):
        restarted.clear(
            actor="operator",
            reconciliation_restart_safe=False,
            unresolved_execution_count=0,
            confirmation="I_ACKNOWLEDGE_RECONCILIATION_IS_CLEAN",
        )
    with pytest.raises(RuntimeError, match="unresolved executions"):
        restarted.clear(
            actor="operator",
            reconciliation_restart_safe=True,
            unresolved_execution_count=1,
            confirmation="I_ACKNOWLEDGE_RECONCILIATION_IS_CLEAN",
        )

    cleared = restarted.clear(
        actor="operator",
        reconciliation_restart_safe=True,
        unresolved_execution_count=0,
        confirmation="I_ACKNOWLEDGE_RECONCILIATION_IS_CLEAN",
    )
    assert cleared.active is False
    assert PersistentExecutionKillSwitch(_database(tmp_path / "kill-switch.db")).state().active is False


def test_paper_broker_accounts_for_costs_funding_idempotency_and_restart(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "paper.db"
    broker = RestartSafePaperBroker(database=_database(database_path), account_id="strategy-a")
    entry = MarketEvent(
        timestamp_ms=1_000,
        symbol="BTCUSDT",
        bid=49_990.0,
        ask=50_010.0,
        volume=100.0,
        funding_rate=0.0001,
        funding_interval_hours=8.0,
    )
    fill = broker.execute(
        fill_id="paper-fill-1",
        event=entry,
        side=Side.BUY,
        quantity=0.01,
        reason="trend_entry",
    )
    duplicate = broker.execute(
        fill_id="paper-fill-1",
        event=entry,
        side=Side.BUY,
        quantity=0.01,
        reason="trend_entry",
    )
    assert fill["fee"] > 0
    assert fill["slippage_cost"] > 0
    assert fill["spread_cost"] > 0
    assert duplicate["duplicate"] is True

    eight_hours_later = MarketEvent(
        timestamp_ms=1_000 + 8 * 60 * 60 * 1_000,
        symbol="BTCUSDT",
        bid=50_990.0,
        ask=51_010.0,
        volume=100.0,
        funding_rate=0.0001,
        funding_interval_hours=8.0,
    )
    broker.mark(eight_hours_later)

    restarted = RestartSafePaperBroker(
        database=_database(database_path),
        account_id="strategy-a",
    )
    snapshot = restarted.snapshot({"BTCUSDT": 51_000.0})
    assert snapshot["restart_safe"] is True
    assert snapshot["total_funding"] > 0
    assert len(snapshot["fills"]) == 1

    exit_fill = restarted.execute(
        fill_id="paper-fill-2",
        event=eight_hours_later,
        side=Side.SELL,
        quantity=0.01,
        reason="trend_exit",
    )
    final = restarted.snapshot()
    assert exit_fill["realized_pnl"] > 0
    assert final["positions"] == {}
    assert final["total_fees"] > fill["fee"]
    assert final["total_slippage"] > fill["slippage_cost"]


def test_strategy_suite_compares_all_required_strategies_with_costs() -> None:
    events = tuple(
        MarketEvent(
            timestamp_ms=index * 1_000,
            symbol="BTCUSDT",
            bid=100.0 + index * 0.25,
            ask=100.1 + index * 0.25,
            volume=10_000.0,
            funding_rate=0.00001,
        )
        for index in range(1, 121)
    )
    report = evaluate_strategy_suite(
        events,
        backtest_config=BacktestConfig(
            initial_cash=10_000.0,
            minimum_notional=25.0,
            max_position_percent=10.0,
        ),
        suite_config=StrategySuiteConfig(
            trend_short_window=5,
            trend_long_window=15,
            breakout_entry_window=10,
            breakout_exit_window=5,
            mean_reversion_window=10,
            minimum_trades=1,
        ),
    )
    assert {item.strategy for item in report.rankings} == {
        "buy_and_hold",
        "trend",
        "breakout",
        "mean_reversion",
    }
    assert report.automatic_promotion is False
    assert all(item.total_fees >= 0 for item in report.rankings)
    assert all(item.total_slippage_cost >= 0 for item in report.rankings)
    assert all(item.total_funding_cost >= 0 for item in report.rankings)


def _fill(match_id: str, source: str, *, price_offset: float = 0.0) -> FillObservation:
    return FillObservation(
        match_id=match_id,
        source=source,
        symbol="BTCUSDT",
        side="BUY",
        submitted_at_ms=1_000,
        first_fill_at_ms=1_100 if source == "paper" else 1_150,
        completed_at_ms=1_200,
        requested_quantity=0.001,
        filled_quantity=0.001,
        reference_price=50_000.0,
        average_fill_price=50_001.0 + price_offset,
        fee=0.05,
        status="Filled",
    )


def test_shadow_validation_requires_fill_equivalence_and_clean_execution_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EXECUTION_KILL_SWITCH", "0")
    database = _database(tmp_path / "shadow.db")
    validator = ShadowExecutionValidator(database=database)
    paper = [_fill(f"match-{index}", "paper") for index in range(20)]
    testnet = [_fill(f"match-{index}", "testnet", price_offset=0.05) for index in range(20)]

    report = validator.validate(
        paper,
        testnet,
        experiment_id="exp-phase13",
        actor="qa",
        report_id="shadow-phase13",
        created_at_ms=10_000,
    )
    assert report.matched_count == 20
    assert report.shadow_eligible is True
    assert report.controlled_live_eligible is False
    assert report.failed_gates == ()
    assert len(report.evidence_sha256) == 64
