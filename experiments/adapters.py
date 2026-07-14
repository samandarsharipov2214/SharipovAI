"""Adapters from canonical research objects into Experiment Registry documents."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from typing import Any, Mapping


def manifest_for_experiment(
    manifest: Any,
    *,
    validated: bool,
    validation_report_id: str = "",
) -> dict[str, Any]:
    """Convert ``DataManifest`` or its mapping into stable registry identity.

    Historical manifests keep per-file hashes in ``sha256``.  Experiment identity
    additionally needs a digest of the complete manifest; this adapter computes it
    without discarding the original file-hash mapping.
    """

    if hasattr(manifest, "to_dict") and callable(manifest.to_dict):
        payload = manifest.to_dict()
    elif is_dataclass(manifest):
        payload = asdict(manifest)
    elif isinstance(manifest, Mapping):
        payload = dict(manifest)
    else:
        raise TypeError("manifest must be a DataManifest or mapping")
    normalized = json.loads(
        json.dumps(payload, ensure_ascii=False, allow_nan=False, sort_keys=True)
    )
    dataset_id = str(
        normalized.get("dataset_id") or normalized.get("manifest_id") or ""
    ).strip()
    dataset_version = str(
        normalized.get("dataset_version") or normalized.get("version") or ""
    ).strip()
    if not dataset_id or not dataset_version:
        raise ValueError("manifest dataset_id and dataset_version are required")
    file_hashes = normalized.get("sha256")
    if file_hashes is None:
        file_hashes = {}
    if not isinstance(file_hashes, Mapping):
        raise ValueError("historical manifest sha256 must be a file-hash mapping")
    canonical_json = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "manifest_id": dataset_id,
        "version": dataset_version,
        "sha256": hashlib.sha256(canonical_json).hexdigest(),
        "validated": bool(validated),
        "validation_report_id": str(validation_report_id).strip(),
        "schema_version": normalized.get("schema_version"),
        "venue": normalized.get("venue"),
        "market_type": normalized.get("market_type"),
        "source": normalized.get("source"),
        "symbols": list(normalized.get("symbols") or []),
        "interval_ms": normalized.get("interval_ms"),
        "start_timestamp_ms": normalized.get("start_timestamp_ms"),
        "end_timestamp_ms": normalized.get("end_timestamp_ms"),
        "row_count": normalized.get("row_count"),
        "parquet_files": list(normalized.get("parquet_files") or []),
        "file_sha256": dict(file_hashes),
        "funding_included": bool(normalized.get("funding_included", False)),
        "manifest_commit_sha": str(normalized.get("commit_sha") or "").strip(),
    }


__all__ = ["manifest_for_experiment"]
