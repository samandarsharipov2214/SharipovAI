from __future__ import annotations

from experiments import ExperimentRegistry, manifest_for_experiment
from historical_data import DataManifest
from storage import ProjectDatabase


def test_canonical_data_manifest_adapts_without_losing_file_hashes(tmp_path) -> None:
    manifest = DataManifest(
        schema_version=1,
        dataset_id="bybit-btc-linear-1m",
        dataset_version="2026-07-v1",
        venue="bybit",
        market_type="linear",
        source="verified-export",
        symbols=("BTCUSDT",),
        interval_ms=60_000,
        timezone="UTC",
        start_timestamp_ms=1_000_000,
        end_timestamp_ms=1_060_000,
        row_count=2,
        parquet_files=("btc.parquet",),
        sha256={"btc.parquet": "a" * 64},
        funding_included=True,
        commit_sha="9d4ec8a",
    )

    adapted = manifest_for_experiment(
        manifest,
        validated=True,
        validation_report_id="validation-1",
    )

    assert adapted["manifest_id"] == "bybit-btc-linear-1m"
    assert adapted["version"] == "2026-07-v1"
    assert len(adapted["sha256"]) == 64
    assert adapted["file_sha256"] == {"btc.parquet": "a" * 64}
    assert adapted["validated"] is True

    database = ProjectDatabase(f"sqlite:///{tmp_path / 'project.db'}")
    experiment = ExperimentRegistry(database).create(
        experiment_id="exp-manifest-adapter",
        commit_sha="9d4ec8a",
        manifest=adapted,
        strategy_name="candidate",
        strategy_config={},
        backtest_config={},
    )
    assert experiment["manifest"]["file_sha256"] == {
        "btc.parquet": "a" * 64
    }
