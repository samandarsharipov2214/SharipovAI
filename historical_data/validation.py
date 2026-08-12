"""Fail-closed validation for versioned Parquet market datasets."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import duckdb

from .manifest import DataManifest


@dataclass(frozen=True, slots=True)
class DatasetValidationIssue:
    code: str
    detail: str
    severity: str = "error"


@dataclass(frozen=True, slots=True)
class DatasetValidationReport:
    status: str
    dataset_id: str
    row_count: int
    min_timestamp_ms: int
    max_timestamp_ms: int
    symbols: tuple[str, ...]
    columns: tuple[str, ...]
    duplicate_rows: int
    invalid_price_rows: int
    missing_interval_count: int
    issues: tuple[DatasetValidationIssue, ...] = field(default_factory=tuple)
    final_oos_eligible: bool = False
    oos_blockers: tuple[str, ...] = field(default_factory=tuple)
    symbol_coverage_mismatch_count: int = 0
    irregular_interval_count: int = 0

    @property
    def valid(self) -> bool:
        return self.status == "ok"


def validate_dataset(
    manifest: DataManifest,
    *,
    root: str | Path,
    connection: duckdb.DuckDBPyConnection | None = None,
) -> DatasetValidationReport:
    """Validate files, schema, hashes, ranges and bar continuity.

    ``valid`` preserves the legacy diagnostic/loading contract. Final OOS is a
    stronger claim: provenance must be complete, each symbol must span the full
    manifest range, bar cadence must be exact, and timestamp semantics must match
    the executable price representation.
    """

    dataset_root = Path(root).resolve()
    files = tuple((dataset_root / item).resolve() for item in manifest.parquet_files)
    issues: list[DatasetValidationIssue] = []
    provenance_blockers = list(manifest.provenance_issues())
    for path in files:
        if dataset_root not in path.parents:
            issues.append(DatasetValidationIssue("unsafe_path", f"{path} escapes dataset root"))
        elif not path.is_file():
            issues.append(DatasetValidationIssue("missing_file", f"{path.name} does not exist"))
    for relative, expected in manifest.sha256.items():
        path = (dataset_root / relative).resolve()
        if path.is_file():
            actual = _sha256(path)
            if actual != expected:
                issues.append(
                    DatasetValidationIssue(
                        "hash_mismatch",
                        f"{relative}: expected {expected}, found {actual}",
                    )
                )

    if issues:
        blockers = _unique(("dataset_validation_failed", *provenance_blockers))
        return DatasetValidationReport(
            status="blocked",
            dataset_id=manifest.dataset_id,
            row_count=0,
            min_timestamp_ms=0,
            max_timestamp_ms=0,
            symbols=(),
            columns=(),
            duplicate_rows=0,
            invalid_price_rows=0,
            missing_interval_count=0,
            issues=tuple(issues),
            final_oos_eligible=False,
            oos_blockers=blockers,
        )

    owns_connection = connection is None
    db = connection or duckdb.connect(database=":memory:")
    try:
        relation = _read_parquet_sql(files)
        description = db.execute(f"DESCRIBE SELECT * FROM {relation}").fetchall()
        columns = tuple(str(row[0]) for row in description)
        missing_required = sorted(set(manifest.required_columns) - set(columns))
        if missing_required:
            issues.append(
                DatasetValidationIssue(
                    "missing_columns",
                    f"missing required columns: {missing_required}",
                )
            )
            return DatasetValidationReport(
                status="blocked",
                dataset_id=manifest.dataset_id,
                row_count=0,
                min_timestamp_ms=0,
                max_timestamp_ms=0,
                symbols=(),
                columns=columns,
                duplicate_rows=0,
                invalid_price_rows=0,
                missing_interval_count=0,
                issues=tuple(issues),
                final_oos_eligible=False,
                oos_blockers=_unique(("dataset_validation_failed", *provenance_blockers)),
            )

        has_quotes = {"bid", "ask"}.issubset(columns)
        has_close = "close" in columns
        if not has_quotes and not has_close:
            issues.append(
                DatasetValidationIssue(
                    "missing_prices",
                    "dataset requires bid+ask or close",
                )
            )

        row = db.execute(
            f"""
            SELECT COUNT(*)::BIGINT,
                   COALESCE(MIN(timestamp_ms), 0)::BIGINT,
                   COALESCE(MAX(timestamp_ms), 0)::BIGINT
            FROM {relation}
            """
        ).fetchone()
        row_count = int(row[0])
        min_timestamp = int(row[1])
        max_timestamp = int(row[2])
        symbols = tuple(
            str(item[0])
            for item in db.execute(
                f"SELECT DISTINCT symbol FROM {relation} ORDER BY symbol"
            ).fetchall()
        )
        coverage_rows = tuple(
            (str(item[0]), int(item[1]), int(item[2]))
            for item in db.execute(
                f"""
                SELECT symbol, MIN(timestamp_ms)::BIGINT, MAX(timestamp_ms)::BIGINT
                FROM {relation}
                GROUP BY symbol
                ORDER BY symbol
                """
            ).fetchall()
        )
        coverage_mismatches = tuple(
            (symbol, start_ms, end_ms)
            for symbol, start_ms, end_ms in coverage_rows
            if start_ms != manifest.start_timestamp_ms or end_ms != manifest.end_timestamp_ms
        )
        duplicates = int(
            db.execute(
                f"""
                SELECT COUNT(*) FROM (
                    SELECT timestamp_ms, symbol, COUNT(*) AS count_value
                    FROM {relation}
                    GROUP BY timestamp_ms, symbol
                    HAVING COUNT(*) > 1
                )
                """
            ).fetchone()[0]
        )
        if has_quotes:
            invalid_prices = int(
                db.execute(
                    f"""
                    SELECT COUNT(*) FROM {relation}
                    WHERE bid IS NULL OR ask IS NULL
                       OR NOT isfinite(bid) OR NOT isfinite(ask)
                       OR bid <= 0 OR ask <= 0 OR ask < bid
                    """
                ).fetchone()[0]
            )
        elif has_close:
            invalid_prices = int(
                db.execute(
                    f"""
                    SELECT COUNT(*) FROM {relation}
                    WHERE close IS NULL OR NOT isfinite(close) OR close <= 0
                    """
                ).fetchone()[0]
            )
        else:
            invalid_prices = row_count

        cadence_rows = tuple(
            int(item[0])
            for item in db.execute(
                f"""
                SELECT timestamp_ms - previous_timestamp AS delta_ms
                FROM (
                    SELECT symbol, timestamp_ms,
                           LAG(timestamp_ms) OVER (
                               PARTITION BY symbol ORDER BY timestamp_ms
                           ) AS previous_timestamp
                    FROM {relation}
                )
                WHERE previous_timestamp IS NOT NULL
                """
            ).fetchall()
        )
        missing_intervals = sum(delta > manifest.interval_ms for delta in cadence_rows)
        # For canonical bar data every adjacent bar must land exactly one interval
        # apart. Short/irregular deltas are not "missing" but are still unsuitable
        # for a final OOS candle claim. Point-in-time quote datasets may be denser.
        irregular_intervals = (
            sum(delta != manifest.interval_ms for delta in cadence_rows)
            if has_close and not has_quotes
            else 0
        )

        if row_count != manifest.row_count:
            issues.append(
                DatasetValidationIssue(
                    "row_count_mismatch",
                    f"manifest={manifest.row_count}, actual={row_count}",
                )
            )
        if min_timestamp != manifest.start_timestamp_ms:
            issues.append(
                DatasetValidationIssue(
                    "start_timestamp_mismatch",
                    f"manifest={manifest.start_timestamp_ms}, actual={min_timestamp}",
                )
            )
        if max_timestamp != manifest.end_timestamp_ms:
            issues.append(
                DatasetValidationIssue(
                    "end_timestamp_mismatch",
                    f"manifest={manifest.end_timestamp_ms}, actual={max_timestamp}",
                )
            )
        if set(symbols) != set(manifest.symbols):
            issues.append(
                DatasetValidationIssue(
                    "symbol_mismatch",
                    f"manifest={manifest.symbols}, actual={symbols}",
                )
            )
        if coverage_mismatches:
            detail = "; ".join(
                f"{symbol}:{start_ms}..{end_ms}"
                for symbol, start_ms, end_ms in coverage_mismatches
            )
            issues.append(
                DatasetValidationIssue(
                    "symbol_coverage_mismatch",
                    "symbols do not span full manifest range: " + detail,
                    severity="warning",
                )
            )
        if duplicates:
            issues.append(
                DatasetValidationIssue(
                    "duplicate_bars",
                    f"duplicate timestamp+symbol groups={duplicates}",
                )
            )
        if invalid_prices:
            issues.append(
                DatasetValidationIssue(
                    "invalid_prices",
                    f"invalid price rows={invalid_prices}",
                )
            )
        if missing_intervals:
            issues.append(
                DatasetValidationIssue(
                    "missing_intervals",
                    f"gaps larger than interval={missing_intervals}",
                    severity="warning",
                )
            )
        if irregular_intervals:
            issues.append(
                DatasetValidationIssue(
                    "irregular_bar_intervals",
                    f"bar deltas different from interval={irregular_intervals}",
                    severity="warning",
                )
            )
        for blocker in provenance_blockers:
            issues.append(
                DatasetValidationIssue(
                    "provenance_incomplete",
                    blocker,
                    severity="warning",
                )
            )

        hard_errors = [item for item in issues if item.severity == "error"]
        oos_blockers: list[str] = list(provenance_blockers)
        if hard_errors:
            oos_blockers.append("dataset_validation_failed")
        if coverage_mismatches:
            oos_blockers.append("symbol_coverage_incomplete")
        if missing_intervals:
            oos_blockers.append("missing_intervals_present")
        if irregular_intervals:
            oos_blockers.append("irregular_bar_intervals_present")
        if has_quotes:
            if manifest.timestamp_semantics != "point_in_time":
                oos_blockers.append("native_bid_ask_requires_point_in_time_timestamps")
        elif has_close:
            if manifest.timestamp_semantics != "bar_close":
                oos_blockers.append("close_prices_require_bar_close_timestamps")
        else:
            oos_blockers.append("executable_price_source_unavailable")
        unique_blockers = _unique(oos_blockers)
        return DatasetValidationReport(
            status="ok" if not hard_errors else "blocked",
            dataset_id=manifest.dataset_id,
            row_count=row_count,
            min_timestamp_ms=min_timestamp,
            max_timestamp_ms=max_timestamp,
            symbols=symbols,
            columns=columns,
            duplicate_rows=duplicates,
            invalid_price_rows=invalid_prices,
            missing_interval_count=missing_intervals,
            issues=tuple(issues),
            final_oos_eligible=not unique_blockers,
            oos_blockers=unique_blockers,
            symbol_coverage_mismatch_count=len(coverage_mismatches),
            irregular_interval_count=irregular_intervals,
        )
    finally:
        if owns_connection:
            db.close()


def _unique(values: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(item) for item in values if item))


def _read_parquet_sql(files: tuple[Path, ...]) -> str:
    quoted = ", ".join("'" + str(path).replace("'", "''") + "'" for path in files)
    return f"read_parquet([{quoted}], union_by_name=true)"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "DatasetValidationIssue",
    "DatasetValidationReport",
    "validate_dataset",
]
