"""Deterministic public Bybit Spot kline importer for Alpha research datasets.

Only public ``/v5/market/kline`` data is read. Bybit timestamps klines by bar
start; canonical SharipovAI rows are timestamped at bar close so close-derived
signals cannot accidentally observe a candle before it is complete.
"""
from __future__ import annotations

import hashlib
import math
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

import duckdb

from exchange_connector.market_data import MarketDataService

from .manifest import DataManifest, validate_manifest
from .validation import DatasetValidationReport, validate_dataset

_BYBIT_KLINE_URL = "https://api.bybit.com/v5/market/kline"
_FIXED_INTERVALS_MINUTES = {1, 3, 5, 15, 30, 60, 120, 240, 360, 720}
_COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True, slots=True)
class BybitSpotImportResult:
    manifest_path: Path
    parquet_path: Path
    manifest: DataManifest
    validation: DatasetValidationReport


class BybitSpotKlineImporter:
    """Build one content-addressed, validation-ready Spot candle dataset."""

    def __init__(self, fetch_json: Callable[..., dict[str, Any]] | None = None) -> None:
        if fetch_json is None:
            service = MarketDataService()
            fetch_json = service.get_json
        self.fetch_json = fetch_json

    def build_dataset(
        self,
        *,
        output_dir: str | Path,
        dataset_id: str,
        dataset_version: str,
        symbols: tuple[str, ...] | list[str],
        interval: str = "15",
        start_bar_open_ms: int,
        end_bar_open_ms: int,
        commit_sha: str,
        retrieved_at_ms: int | None = None,
        default_spread_bps: float = 2.0,
    ) -> BybitSpotImportResult:
        clean_id = _safe_name(dataset_id, "dataset_id")
        clean_version = _safe_name(dataset_version, "dataset_version")
        clean_symbols = tuple(_symbol(item) for item in symbols)
        if not clean_symbols or len(set(clean_symbols)) != len(clean_symbols):
            raise ValueError("symbols must be non-empty and unique")
        interval_ms = _interval_ms(interval)
        start_open = _positive_int(start_bar_open_ms, "start_bar_open_ms")
        end_open = _positive_int(end_bar_open_ms, "end_bar_open_ms")
        if end_open < start_open:
            raise ValueError("end_bar_open_ms precedes start_bar_open_ms")
        if not _COMMIT_SHA.fullmatch(str(commit_sha)):
            raise ValueError("commit_sha must be 40 lowercase hex characters")
        retrieved = (
            int(time.time() * 1000)
            if retrieved_at_ms is None
            else _positive_int(retrieved_at_ms, "retrieved_at_ms")
        )
        if not math.isfinite(float(default_spread_bps)) or not 0 <= float(default_spread_bps) <= 1_000:
            raise ValueError("default_spread_bps must be within 0..1000")

        rows: list[tuple[int, int, str, float, float, float, float, float, float]] = []
        for symbol in clean_symbols:
            symbol_rows = self._fetch_symbol(
                symbol=symbol,
                interval=str(interval),
                interval_ms=interval_ms,
                start_bar_open_ms=start_open,
                end_bar_open_ms=end_open,
                retrieved_at_ms=retrieved,
            )
            if not symbol_rows:
                raise ValueError(f"Bybit returned no fully closed klines for {symbol}")
            rows.extend(symbol_rows)
        rows.sort(key=lambda item: (item[0], item[2]))

        target = Path(output_dir).resolve()
        target.mkdir(parents=True, exist_ok=True)
        parquet_path = target / f"{clean_id}-{clean_version}.parquet"
        manifest_path = target / "manifest.json"
        if parquet_path.exists() or manifest_path.exists():
            raise FileExistsError("historical dataset output is immutable; use a new dataset version")
        _write_parquet(parquet_path, rows)
        digest = _sha256(parquet_path)
        created_at = datetime.fromtimestamp(retrieved / 1000, tz=UTC).isoformat()
        manifest = DataManifest(
            schema_version=1,
            dataset_id=clean_id,
            dataset_version=clean_version,
            venue="bybit",
            market_type="spot",
            source="bybit_v5_market_kline",
            symbols=clean_symbols,
            interval_ms=interval_ms,
            timezone="UTC",
            start_timestamp_ms=min(row[0] for row in rows),
            end_timestamp_ms=max(row[0] for row in rows),
            row_count=len(rows),
            parquet_files=(parquet_path.name,),
            optional_columns=(
                "source_start_timestamp_ms",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "turnover",
            ),
            sha256={parquet_path.name: digest},
            default_spread_bps=float(default_spread_bps),
            funding_included=False,
            created_at=created_at,
            commit_sha=commit_sha,
            timestamp_semantics="bar_close",
        )
        validate_manifest(manifest)
        manifest.save(manifest_path)
        validation = validate_dataset(manifest, root=target)
        if not validation.valid:
            details = "; ".join(
                f"{issue.code}: {issue.detail}"
                for issue in validation.issues
                if issue.severity == "error"
            )
            raise ValueError(f"imported Bybit dataset failed validation: {details}")
        return BybitSpotImportResult(
            manifest_path=manifest_path,
            parquet_path=parquet_path,
            manifest=manifest,
            validation=validation,
        )

    def _fetch_symbol(
        self,
        *,
        symbol: str,
        interval: str,
        interval_ms: int,
        start_bar_open_ms: int,
        end_bar_open_ms: int,
        retrieved_at_ms: int,
    ) -> list[tuple[int, int, str, float, float, float, float, float, float]]:
        by_start: dict[int, tuple[int, int, str, float, float, float, float, float, float]] = {}
        cursor_end = end_bar_open_ms
        for _page in range(10_000):
            payload = self.fetch_json(
                _BYBIT_KLINE_URL,
                params={
                    "category": "spot",
                    "symbol": symbol,
                    "interval": interval,
                    "start": str(start_bar_open_ms),
                    "end": str(cursor_end),
                    "limit": "1000",
                },
            )
            if payload.get("retCode") != 0:
                raise ValueError(f"Bybit kline request failed: {payload.get('retMsg') or payload.get('retCode')}")
            result = payload.get("result")
            raw_rows = result.get("list") if isinstance(result, dict) else None
            if not isinstance(raw_rows, list):
                raise ValueError("Bybit kline response is missing result.list")
            if not raw_rows:
                break

            page_starts: list[int] = []
            for raw in raw_rows:
                parsed = _parse_kline(raw, symbol=symbol, interval_ms=interval_ms)
                source_start = parsed[1]
                page_starts.append(source_start)
                if source_start < start_bar_open_ms or source_start > end_bar_open_ms:
                    continue
                # Bybit documents closePrice on an unclosed candle as the latest
                # traded price. Never admit that mutable candle into immutable
                # historical evidence.
                if parsed[0] > retrieved_at_ms:
                    continue
                previous = by_start.get(source_start)
                if previous is not None and previous != parsed:
                    raise ValueError(f"conflicting duplicate kline for {symbol} at {source_start}")
                by_start[source_start] = parsed

            if not page_starts:
                break
            oldest = min(page_starts)
            if oldest <= start_bar_open_ms:
                break
            next_end = oldest - 1
            if next_end >= cursor_end:
                raise RuntimeError("Bybit kline pagination did not make progress")
            cursor_end = next_end
        else:
            raise RuntimeError("Bybit kline pagination exceeded safety page limit")
        return list(by_start.values())


def _parse_kline(
    raw: Any,
    *,
    symbol: str,
    interval_ms: int,
) -> tuple[int, int, str, float, float, float, float, float, float]:
    if not isinstance(raw, list) or len(raw) < 7:
        raise ValueError("Bybit kline row must contain at least 7 fields")
    start = _positive_int(raw[0], "kline startTime")
    open_price = _positive_float(raw[1], "open")
    high = _positive_float(raw[2], "high")
    low = _positive_float(raw[3], "low")
    close = _positive_float(raw[4], "close")
    volume = _nonnegative_float(raw[5], "volume")
    turnover = _nonnegative_float(raw[6], "turnover")
    if high < max(open_price, low, close) or low > min(open_price, high, close):
        raise ValueError(f"invalid OHLC relation for {symbol} at {start}")
    close_timestamp = start + interval_ms
    return (
        close_timestamp,
        start,
        symbol,
        open_price,
        high,
        low,
        close,
        volume,
        turnover,
    )


def _write_parquet(
    path: Path,
    rows: list[tuple[int, int, str, float, float, float, float, float, float]],
) -> None:
    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute(
            """
            CREATE TABLE imported_bars(
                timestamp_ms BIGINT,
                source_start_timestamp_ms BIGINT,
                symbol VARCHAR,
                open DOUBLE,
                high DOUBLE,
                low DOUBLE,
                close DOUBLE,
                volume DOUBLE,
                turnover DOUBLE
            )
            """
        )
        connection.executemany(
            "INSERT INTO imported_bars VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        escaped = str(path).replace("'", "''")
        connection.execute(
            f"COPY (SELECT * FROM imported_bars ORDER BY timestamp_ms, symbol) "
            f"TO '{escaped}' (FORMAT PARQUET)"
        )
    finally:
        connection.close()


def _interval_ms(value: str) -> int:
    try:
        minutes = int(str(value))
    except ValueError as exc:
        raise ValueError("Alpha importer supports fixed-minute Bybit intervals only") from exc
    if minutes not in _FIXED_INTERVALS_MINUTES:
        raise ValueError("unsupported fixed-minute Bybit interval")
    return minutes * 60_000


def _safe_name(value: str, field: str) -> str:
    clean = str(value).strip()
    if not clean or len(clean) > 100 or not all(character.isalnum() or character in "-_." for character in clean):
        raise ValueError(f"{field} contains unsafe characters")
    return clean


def _symbol(value: str) -> str:
    clean = str(value).strip().upper().replace("/", "").replace("-", "")
    if not clean or len(clean) > 30 or not clean.isalnum():
        raise ValueError("invalid symbol")
    return clean


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be positive")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be positive") from exc
    if parsed <= 0:
        raise ValueError(f"{field} must be positive")
    return parsed


def _positive_float(value: Any, field: str) -> float:
    parsed = _finite_float(value, field)
    if parsed <= 0:
        raise ValueError(f"{field} must be positive")
    return parsed


def _nonnegative_float(value: Any, field: str) -> float:
    parsed = _finite_float(value, field)
    if parsed < 0:
        raise ValueError(f"{field} must be non-negative")
    return parsed


def _finite_float(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be finite")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be finite") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{field} must be finite")
    return parsed


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = ["BybitSpotImportResult", "BybitSpotKlineImporter"]
