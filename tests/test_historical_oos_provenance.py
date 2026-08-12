"""Final-OOS eligibility requires complete historical-data provenance."""
from __future__ import annotations

import hashlib
from pathlib import Path

import duckdb
import pytest

from historical_data import DataManifest, HistoricalDataLoader, validate_dataset


def _write_parquet(path: Path) -> None:
    _write_rows(
        path,
        (
            (1000, "BTCUSDT", 100.0, 1000.0),
            (2000, "BTCUSDT", 101.0, 1100.0),
            (3000, "BTCUSDT", 102.0, 1200.0),
        ),
    )


def _write_rows(
    path: Path,
    rows: tuple[tuple[int, str, float, float], ...],
) -> None:
    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute(
            """
            CREATE TABLE bars(
                timestamp_ms BIGINT,
                symbol VARCHAR,
                close DOUBLE,
                volume DOUBLE
            )
            """
        )
        connection.executemany("INSERT INTO bars VALUES (?, ?, ?, ?)", rows)
        escaped = str(path).replace("'", "''")
        connection.execute(f"COPY bars TO '{escaped}' (FORMAT PARQUET)")
    finally:
        connection.close()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest(path: Path, *, complete: bool, semantics: str = "bar_close") -> DataManifest:
    return DataManifest(
        schema_version=1,
        dataset_id="alpha-fixture",
        dataset_version="v1",
        venue="bybit",
        market_type="spot",
        source="test-fixture",
        symbols=("BTCUSDT",),
        interval_ms=1000,
        timezone="UTC",
        start_timestamp_ms=1000,
        end_timestamp_ms=3000,
        row_count=3,
        parquet_files=(path.name,),
        sha256={path.name: _sha256(path)} if complete else {},
        created_at="2026-08-12T12:00:00+00:00" if complete else "",
        commit_sha="a" * 40 if complete else "",
        timestamp_semantics=semantics if complete else "unknown",
    )


def _complete_manifest(
    path: Path,
    *,
    symbols: tuple[str, ...],
    row_count: int,
    start: int = 1000,
    end: int = 3000,
) -> DataManifest:
    return DataManifest(
        schema_version=1,
        dataset_id="alpha-multi-fixture",
        dataset_version="v1",
        venue="bybit",
        market_type="spot",
        source="test-fixture",
        symbols=symbols,
        interval_ms=1000,
        timezone="UTC",
        start_timestamp_ms=start,
        end_timestamp_ms=end,
        row_count=row_count,
        parquet_files=(path.name,),
        sha256={path.name: _sha256(path)},
        created_at="2026-08-12T12:00:00+00:00",
        commit_sha="a" * 40,
        timestamp_semantics="bar_close",
    )


def test_legacy_dataset_can_validate_without_becoming_final_oos_evidence(tmp_path: Path) -> None:
    parquet = tmp_path / "bars.parquet"
    _write_parquet(parquet)
    manifest = _manifest(parquet, complete=False)

    report = validate_dataset(manifest, root=tmp_path)

    assert report.valid is True
    assert report.final_oos_eligible is False
    assert "timestamp_semantics_unknown" in report.oos_blockers
    assert any(item.startswith("missing_sha256:") for item in report.oos_blockers)
    assert "commit_sha_missing_or_invalid" in report.oos_blockers


def test_complete_bar_close_dataset_is_final_oos_eligible(tmp_path: Path) -> None:
    parquet = tmp_path / "bars.parquet"
    _write_parquet(parquet)
    manifest = _manifest(parquet, complete=True)

    report = validate_dataset(manifest, root=tmp_path)

    assert report.valid is True
    assert report.final_oos_eligible is True
    assert report.oos_blockers == ()
    assert report.symbol_coverage_mismatch_count == 0
    assert report.irregular_interval_count == 0
    assert manifest.final_oos_provenance_complete is True


def test_close_prices_with_bar_open_timestamp_are_not_final_oos_eligible(tmp_path: Path) -> None:
    parquet = tmp_path / "bars.parquet"
    _write_parquet(parquet)
    manifest = _manifest(parquet, complete=True, semantics="bar_open")

    report = validate_dataset(manifest, root=tmp_path)

    assert report.valid is True
    assert report.final_oos_eligible is False
    assert "close_prices_require_bar_close_timestamps" in report.oos_blockers


def test_multi_symbol_dataset_requires_full_boundary_coverage_per_symbol(tmp_path: Path) -> None:
    parquet = tmp_path / "multi.parquet"
    _write_rows(
        parquet,
        (
            (1000, "BTCUSDT", 100.0, 1000.0),
            (2000, "BTCUSDT", 101.0, 1100.0),
            (3000, "BTCUSDT", 102.0, 1200.0),
            # ETH starts late. Global min/max still match the manifest, and there
            # is no internal ETH gap, so only per-symbol coverage catches this.
            (2000, "ETHUSDT", 200.0, 900.0),
            (3000, "ETHUSDT", 201.0, 950.0),
        ),
    )
    manifest = _complete_manifest(
        parquet,
        symbols=("BTCUSDT", "ETHUSDT"),
        row_count=5,
    )

    report = validate_dataset(manifest, root=tmp_path)

    assert report.valid is True
    assert report.missing_interval_count == 0
    assert report.symbol_coverage_mismatch_count == 1
    assert report.final_oos_eligible is False
    assert "symbol_coverage_incomplete" in report.oos_blockers


def test_close_bar_dataset_requires_exact_interval_cadence(tmp_path: Path) -> None:
    parquet = tmp_path / "irregular.parquet"
    _write_rows(
        parquet,
        (
            (1000, "BTCUSDT", 100.0, 1000.0),
            (1500, "BTCUSDT", 100.5, 1000.0),
            (2000, "BTCUSDT", 101.0, 1000.0),
            (3000, "BTCUSDT", 102.0, 1000.0),
        ),
    )
    manifest = _complete_manifest(
        parquet,
        symbols=("BTCUSDT",),
        row_count=4,
    )

    report = validate_dataset(manifest, root=tmp_path)

    assert report.valid is True
    assert report.missing_interval_count == 0
    assert report.irregular_interval_count == 2
    assert report.final_oos_eligible is False
    assert "irregular_bar_intervals_present" in report.oos_blockers


def test_loader_has_explicit_fail_closed_final_oos_gate(tmp_path: Path) -> None:
    parquet = tmp_path / "bars.parquet"
    _write_parquet(parquet)
    manifest_path = tmp_path / "manifest.json"
    _manifest(parquet, complete=False).save(manifest_path)

    with HistoricalDataLoader(manifest_path) as loader:
        with pytest.raises(ValueError, match="not final-OOS eligible"):
            loader.require_final_oos_eligible()

    complete_path = tmp_path / "complete.json"
    _manifest(parquet, complete=True).save(complete_path)
    with HistoricalDataLoader(complete_path) as loader:
        report = loader.require_final_oos_eligible()
        assert report.final_oos_eligible is True
        events = tuple(loader.iter_events())
        assert events[0].metadata["final_oos_eligible"] is True
