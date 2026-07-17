"""Versioned historical-data manifest with explicit provenance."""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class DataManifest:
    schema_version: int
    dataset_id: str
    dataset_version: str
    venue: str
    market_type: str
    source: str
    symbols: tuple[str, ...]
    interval_ms: int
    timezone: str
    start_timestamp_ms: int
    end_timestamp_ms: int
    row_count: int
    parquet_files: tuple[str, ...]
    required_columns: tuple[str, ...] = ("timestamp_ms", "symbol")
    optional_columns: tuple[str, ...] = (
        "bid", "ask", "close", "volume", "funding_rate"
    )
    sha256: Mapping[str, str] = field(default_factory=dict)
    default_spread_bps: float = 2.0
    funding_included: bool = False
    created_at: str = ""
    commit_sha: str = ""

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "DataManifest":
        if not isinstance(payload, Mapping):
            raise TypeError("manifest payload must be a mapping")
        try:
            manifest = cls(
                schema_version=int(payload["schema_version"]),
                dataset_id=str(payload["dataset_id"]).strip(),
                dataset_version=str(payload["dataset_version"]).strip(),
                venue=str(payload["venue"]).strip().lower(),
                market_type=str(payload["market_type"]).strip().lower(),
                source=str(payload["source"]).strip(),
                symbols=tuple(str(item).strip().upper() for item in payload["symbols"]),
                interval_ms=int(payload["interval_ms"]),
                timezone=str(payload.get("timezone", "UTC")).strip(),
                start_timestamp_ms=int(payload["start_timestamp_ms"]),
                end_timestamp_ms=int(payload["end_timestamp_ms"]),
                row_count=int(payload["row_count"]),
                parquet_files=tuple(str(item).strip() for item in payload["parquet_files"]),
                required_columns=tuple(
                    str(item).strip()
                    for item in payload.get("required_columns", ("timestamp_ms", "symbol"))
                ),
                optional_columns=tuple(
                    str(item).strip()
                    for item in payload.get(
                        "optional_columns",
                        ("bid", "ask", "close", "volume", "funding_rate"),
                    )
                ),
                sha256={
                    str(key): str(value).lower()
                    for key, value in dict(payload.get("sha256", {})).items()
                },
                default_spread_bps=float(payload.get("default_spread_bps", 2.0)),
                funding_included=bool(payload.get("funding_included", False)),
                created_at=str(payload.get("created_at", "")).strip(),
                commit_sha=str(payload.get("commit_sha", "")).strip(),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid historical-data manifest: {exc}") from exc
        validate_manifest(manifest)
        return manifest

    @classmethod
    def load(cls, path: str | Path) -> "DataManifest":
        source = Path(path)
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise
        except Exception as exc:
            raise ValueError(f"cannot read manifest {source}: {exc}") from exc
        return cls.from_dict(payload)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["symbols"] = list(self.symbols)
        payload["parquet_files"] = list(self.parquet_files)
        payload["required_columns"] = list(self.required_columns)
        payload["optional_columns"] = list(self.optional_columns)
        payload["sha256"] = dict(self.sha256)
        return payload

    def save(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_suffix(target.suffix + ".tmp")
        temp.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temp.replace(target)


def validate_manifest(manifest: DataManifest) -> None:
    if manifest.schema_version != 1:
        raise ValueError("unsupported historical-data manifest schema_version")
    for name, value in (
        ("dataset_id", manifest.dataset_id),
        ("dataset_version", manifest.dataset_version),
        ("venue", manifest.venue),
        ("market_type", manifest.market_type),
        ("source", manifest.source),
        ("timezone", manifest.timezone),
    ):
        if not value:
            raise ValueError(f"manifest {name} is required")
    if not manifest.symbols or len(set(manifest.symbols)) != len(manifest.symbols):
        raise ValueError("manifest symbols must be non-empty and unique")
    if any(not symbol.isalnum() or symbol != symbol.upper() for symbol in manifest.symbols):
        raise ValueError("manifest symbols must be uppercase alphanumeric")
    if manifest.interval_ms <= 0:
        raise ValueError("manifest interval_ms must be positive")
    if manifest.start_timestamp_ms <= 0:
        raise ValueError("manifest start_timestamp_ms must be positive")
    if manifest.end_timestamp_ms < manifest.start_timestamp_ms:
        raise ValueError("manifest end_timestamp_ms precedes start")
    if manifest.row_count <= 0:
        raise ValueError("manifest row_count must be positive")
    if not manifest.parquet_files:
        raise ValueError("manifest parquet_files must be non-empty")
    if len(set(manifest.parquet_files)) != len(manifest.parquet_files):
        raise ValueError("manifest parquet_files must be unique")
    if any(
        not item or Path(item).is_absolute() or ".." in Path(item).parts
        for item in manifest.parquet_files
    ):
        raise ValueError("manifest parquet_files must be safe relative paths")
    required = set(manifest.required_columns)
    if not {"timestamp_ms", "symbol"}.issubset(required):
        raise ValueError("manifest must require timestamp_ms and symbol")
    if not math.isfinite(manifest.default_spread_bps):
        raise ValueError("default_spread_bps must be finite")
    if not 0 <= manifest.default_spread_bps <= 1_000:
        raise ValueError("default_spread_bps must be within 0..1000")
    for filename, digest in manifest.sha256.items():
        if filename not in manifest.parquet_files:
            raise ValueError("sha256 contains a file absent from parquet_files")
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ValueError("manifest sha256 values must be lowercase hex")


__all__ = ["DataManifest", "validate_manifest"]
