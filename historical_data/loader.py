"""DuckDB-backed Parquet loader for canonical MarketEvent streams."""
from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import duckdb

from trading_core import MarketEvent

from .manifest import DataManifest
from .validation import DatasetValidationReport, validate_dataset


class HistoricalDataLoader:
    """Load validated Parquet bars without pandas or in-memory file copies."""

    def __init__(
        self,
        manifest_path: str | Path,
        *,
        dataset_root: str | Path | None = None,
        validate_on_open: bool = True,
    ) -> None:
        self.manifest_path = Path(manifest_path).resolve()
        self.manifest = DataManifest.load(self.manifest_path)
        self.dataset_root = (
            Path(dataset_root).resolve()
            if dataset_root is not None
            else self.manifest_path.parent
        )
        self.connection = duckdb.connect(database=":memory:")
        self.validation_report: DatasetValidationReport | None = None
        if validate_on_open:
            self.validation_report = self.validate()
            if not self.validation_report.valid:
                details = "; ".join(
                    f"{item.code}: {item.detail}"
                    for item in self.validation_report.issues
                    if item.severity == "error"
                )
                raise ValueError(f"historical dataset validation failed: {details}")

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "HistoricalDataLoader":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def validate(self) -> DatasetValidationReport:
        self.validation_report = validate_dataset(
            self.manifest,
            root=self.dataset_root,
            connection=self.connection,
        )
        try:
            from observability.metrics import record_dataset_validation

            record_dataset_validation(self.validation_report)
        except Exception:
            pass
        return self.validation_report

    def iter_events(
        self,
        *,
        symbols: Sequence[str] | None = None,
        start_timestamp_ms: int | None = None,
        end_timestamp_ms: int | None = None,
        limit: int | None = None,
    ) -> Iterator[MarketEvent]:
        """Yield events ordered by timestamp and symbol for deterministic replay."""

        selected_symbols = tuple(
            str(item).strip().upper()
            for item in (symbols or self.manifest.symbols)
        )
        if not selected_symbols:
            raise ValueError("at least one symbol is required")
        unknown = sorted(set(selected_symbols) - set(self.manifest.symbols))
        if unknown:
            raise ValueError(f"symbols absent from manifest: {unknown}")
        if start_timestamp_ms is not None and start_timestamp_ms <= 0:
            raise ValueError("start_timestamp_ms must be positive")
        if end_timestamp_ms is not None and end_timestamp_ms <= 0:
            raise ValueError("end_timestamp_ms must be positive")
        if (
            start_timestamp_ms is not None
            and end_timestamp_ms is not None
            and end_timestamp_ms < start_timestamp_ms
        ):
            raise ValueError("end_timestamp_ms precedes start_timestamp_ms")
        if limit is not None and limit <= 0:
            raise ValueError("limit must be positive")

        relation = _read_parquet_sql(self._files())
        columns = self._columns(relation)
        bid_sql, ask_sql = self._price_expressions(columns)
        volume_sql = "CAST(volume AS DOUBLE)" if "volume" in columns else "NULL"
        funding_sql = (
            "COALESCE(CAST(funding_rate AS DOUBLE), 0.0)"
            if "funding_rate" in columns
            else "0.0"
        )
        funding_interval_sql = (
            "COALESCE(CAST(funding_interval_hours AS DOUBLE), 8.0)"
            if "funding_interval_hours" in columns
            else "8.0"
        )
        placeholders = ", ".join("?" for _ in selected_symbols)
        where = [f"symbol IN ({placeholders})"]
        parameters: list[Any] = list(selected_symbols)
        if start_timestamp_ms is not None:
            where.append("timestamp_ms >= ?")
            parameters.append(int(start_timestamp_ms))
        if end_timestamp_ms is not None:
            where.append("timestamp_ms <= ?")
            parameters.append(int(end_timestamp_ms))
        limit_sql = ""
        if limit is not None:
            limit_sql = " LIMIT ?"
            parameters.append(int(limit))

        rows = self.connection.execute(
            f"""
            SELECT
                CAST(timestamp_ms AS BIGINT) AS timestamp_ms,
                UPPER(CAST(symbol AS VARCHAR)) AS symbol,
                {bid_sql} AS bid,
                {ask_sql} AS ask,
                {volume_sql} AS volume,
                {funding_sql} AS funding_rate,
                {funding_interval_sql} AS funding_interval_hours
            FROM {relation}
            WHERE {' AND '.join(where)}
            ORDER BY timestamp_ms, symbol
            {limit_sql}
            """,
            parameters,
        ).fetchall()
        for row in rows:
            yield MarketEvent(
                timestamp_ms=int(row[0]),
                symbol=str(row[1]),
                bid=float(row[2]),
                ask=float(row[3]),
                source=(
                    f"{self.manifest.venue}:"
                    f"{self.manifest.dataset_id}:"
                    f"{self.manifest.dataset_version}"
                ),
                volume=float(row[4]) if row[4] is not None else None,
                funding_rate=float(row[5]),
                funding_interval_hours=float(row[6]),
                metadata={
                    "dataset_id": self.manifest.dataset_id,
                    "dataset_version": self.manifest.dataset_version,
                    "venue": self.manifest.venue,
                    "market_type": self.manifest.market_type,
                    "manifest": str(self.manifest_path),
                },
            )

    def rows(
        self,
        *,
        columns: Sequence[str],
        limit: int = 1_000,
    ) -> tuple[dict[str, Any], ...]:
        """Return bounded diagnostic rows for tooling and tests."""

        if not columns:
            raise ValueError("columns must be non-empty")
        if limit <= 0 or limit > 100_000:
            raise ValueError("limit must be within 1..100000")
        relation = _read_parquet_sql(self._files())
        available = self._columns(relation)
        requested = tuple(str(item).strip() for item in columns)
        unknown = sorted(set(requested) - set(available))
        if unknown:
            raise ValueError(f"unknown dataset columns: {unknown}")
        quoted = ", ".join(_quote_identifier(item) for item in requested)
        result = self.connection.execute(
            f"""
            SELECT {quoted}
            FROM {relation}
            ORDER BY timestamp_ms, symbol
            LIMIT ?
            """,
            [limit],
        )
        return tuple(
            dict(zip(requested, row, strict=True))
            for row in result.fetchall()
        )

    def _files(self) -> tuple[Path, ...]:
        return tuple(
            (self.dataset_root / item).resolve()
            for item in self.manifest.parquet_files
        )

    def _columns(self, relation: str) -> set[str]:
        return {
            str(row[0])
            for row in self.connection.execute(
                f"DESCRIBE SELECT * FROM {relation}"
            ).fetchall()
        }

    def _price_expressions(self, columns: set[str]) -> tuple[str, str]:
        if {"bid", "ask"}.issubset(columns):
            return "CAST(bid AS DOUBLE)", "CAST(ask AS DOUBLE)"
        if "close" not in columns:
            raise ValueError("dataset requires bid+ask or close")
        half_spread = self.manifest.default_spread_bps / 20_000.0
        return (
            f"CAST(close AS DOUBLE) * {1.0 - half_spread:.16f}",
            f"CAST(close AS DOUBLE) * {1.0 + half_spread:.16f}",
        )


def _read_parquet_sql(files: tuple[Path, ...]) -> str:
    quoted = ", ".join(
        "'" + str(path).replace("'", "''") + "'"
        for path in files
    )
    return f"read_parquet([{quoted}], union_by_name=true)"


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


__all__ = ["HistoricalDataLoader"]
