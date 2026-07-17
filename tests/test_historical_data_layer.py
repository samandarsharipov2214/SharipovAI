from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from historical_data import DataManifest, HistoricalDataLoader, validate_dataset


def _write_parquet(path: Path, *, duplicate: bool = False) -> None:
    connection = duckdb.connect(database=":memory:")
    rows = (
        "(1000, 'BTCUSDT', 100.0, 1000.0, 0.0001),"
        "(1000, 'BTCUSDT', 101.0, 1000.0, 0.0001),"
        "(3000, 'BTCUSDT', 102.0, 1000.0, 0.0001)"
        if duplicate
        else
        "(1000, 'BTCUSDT', 100.0, 1000.0, 0.0001),"
        "(2000, 'BTCUSDT', 101.0, 1000.0, 0.0001),"
        "(3000, 'BTCUSDT', 102.0, 1000.0, 0.0001)"
    )
    connection.execute(
        f"""
        CREATE TABLE bars(
            timestamp_ms BIGINT,
            symbol VARCHAR,
            close DOUBLE,
            volume DOUBLE,
            funding_rate DOUBLE
        );
        INSERT INTO bars VALUES {rows};
        COPY bars TO '{str(path).replace("'", "''")}' (FORMAT PARQUET);
        """
    )
    connection.close()


def _manifest(path: Path) -> DataManifest:
    return DataManifest(
        schema_version=1,
        dataset_id="btc-test",
        dataset_version="v1",
        venue="bybit",
        market_type="linear",
        source="test-fixture",
        symbols=("BTCUSDT",),
        interval_ms=1000,
        timezone="UTC",
        start_timestamp_ms=1000,
        end_timestamp_ms=3000,
        row_count=3,
        parquet_files=(path.name,),
        default_spread_bps=4.0,
        funding_included=True,
    )


def test_duckdb_loader_validates_manifest_and_yields_events(tmp_path: Path) -> None:
    parquet = tmp_path / "bars.parquet"
    _write_parquet(parquet)
    manifest_path = tmp_path / "manifest.json"
    _manifest(parquet).save(manifest_path)

    with HistoricalDataLoader(manifest_path) as loader:
        events = tuple(loader.iter_events())

    assert len(events) == 3
    assert events[0].symbol == "BTCUSDT"
    assert events[0].bid < 100.0 < events[0].ask
    assert events[0].funding_rate == pytest.approx(0.0001)
    assert events[0].metadata["dataset_id"] == "btc-test"


def test_dataset_validation_blocks_duplicate_bars(tmp_path: Path) -> None:
    parquet = tmp_path / "bars.parquet"
    _write_parquet(parquet, duplicate=True)
    manifest = _manifest(parquet)

    report = validate_dataset(manifest, root=tmp_path)

    assert report.valid is False
    assert report.duplicate_rows == 1
    assert any(issue.code == "duplicate_bars" for issue in report.issues)


def test_manifest_rejects_unsafe_relative_paths() -> None:
    with pytest.raises(ValueError, match="safe relative paths"):
        DataManifest.from_dict(
            {
                "schema_version": 1,
                "dataset_id": "unsafe",
                "dataset_version": "v1",
                "venue": "bybit",
                "market_type": "linear",
                "source": "test",
                "symbols": ["BTCUSDT"],
                "interval_ms": 1000,
                "start_timestamp_ms": 1000,
                "end_timestamp_ms": 2000,
                "row_count": 2,
                "parquet_files": ["../escape.parquet"],
            }
        )
