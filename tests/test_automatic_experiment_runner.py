from __future__ import annotations

import json

import duckdb
import pytest

from experiments import (
    AutomaticExperimentRequest,
    AutomaticExperimentRunner,
    ImmutableExperimentResultStore,
)
from storage import ProjectDatabase
from trading_core import BacktestConfig, BuyAndHoldStrategy, WalkForwardConfig


def _database(tmp_path) -> ProjectDatabase:
    return ProjectDatabase(f"sqlite:///{tmp_path / 'project.db'}")


def _dataset(tmp_path):
    parquet = tmp_path / "btc.parquet"
    escaped = str(parquet).replace("'", "''")
    connection = duckdb.connect()
    connection.execute(
        f"""
        COPY (
            SELECT
                1_700_000_000_000 + i * 60_000 AS timestamp_ms,
                'BTCUSDT' AS symbol,
                100.0 + i * 0.2 AS close,
                1000000.0 AS volume,
                0.0001 AS funding_rate
            FROM range(100) AS generated(i)
        ) TO '{escaped}' (FORMAT PARQUET)
        """
    )
    connection.close()
    manifest = {
        "schema_version": 1,
        "dataset_id": "btc-runner-test",
        "dataset_version": "v1",
        "venue": "bybit",
        "market_type": "spot",
        "source": "test-fixture",
        "symbols": ["BTCUSDT"],
        "interval_ms": 60_000,
        "timezone": "UTC",
        "start_timestamp_ms": 1_700_000_000_000,
        "end_timestamp_ms": 1_700_000_000_000 + 99 * 60_000,
        "row_count": 100,
        "parquet_files": ["btc.parquet"],
        "required_columns": ["timestamp_ms", "symbol"],
        "optional_columns": ["close", "volume", "funding_rate"],
        "default_spread_bps": 2.0,
        "funding_included": True,
        "sha256": {},
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def test_runner_creates_completed_experiment_and_write_once_results(tmp_path) -> None:
    database = _database(tmp_path)
    runner = AutomaticExperimentRunner(database=database)
    request = AutomaticExperimentRequest(
        commit_sha="d28de813188e93603fe3384ebe3926d97fb916a3",
        strategy_name="candidate_buy_hold",
        strategy_config={"risk_percent": 1.0},
        backtest_config=BacktestConfig(
            initial_cash=1_000.0,
            minimum_notional=5.0,
            market_impact_bps=1.0,
        ),
        walk_forward_config=WalkForwardConfig(
            train_events=20,
            test_events=10,
            step_events=10,
            minimum_windows=6,
            anchored=False,
            chain_capital=True,
        ),
        manifest_path=str(_dataset(tmp_path)),
    )

    completed = runner.run(
        request,
        walk_forward_strategy_factory=lambda _train, _index: BuyAndHoldStrategy(),
        benchmark_strategy_factory=lambda: BuyAndHoldStrategy(),
    )

    assert completed["status"] == "completed"
    assert set(completed["results"]) == {
        "data_validation",
        "walk_forward",
        "benchmarks",
        "run_summary",
    }
    assert completed["results"]["walk_forward"]["immutable_sha256"]
    store = ImmutableExperimentResultStore(database)
    stored = store.get(completed["experiment_id"], "walk_forward")
    assert stored is not None
    assert stored["immutable"] is True

    with pytest.raises(RuntimeError, match="same immutable"):
        runner.run(
            request,
            walk_forward_strategy_factory=lambda _train, _index: BuyAndHoldStrategy(),
            benchmark_strategy_factory=lambda: BuyAndHoldStrategy(),
        )
