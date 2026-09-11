"""Canonical one-shot claims for overlapping final-OOS ranges of a dataset.

Receipts beside manifests are exportable evidence, not the authority for whether
data was inspected. Claims share ProjectDatabase across working directories.
This protects a manifest digest; aliases with different digests and research
outside this runner still require explicit provenance review.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from storage import ProjectDatabase

from .alpha_experiment import AlphaExperiment

_NAMESPACE = "alpha_holdout_consumption"


class FinalOOSAlreadyConsumed(RuntimeError):
    """Raised when any of the requested dataset holdout was already opened."""


def final_oos_identity(experiment: AlphaExperiment) -> str:
    """Content identity independent of experiment name or result filename."""

    payload = (
        f"{experiment.dataset_manifest_sha256}:"
        f"{experiment.final_oos_range[0]}:{experiment.final_oos_range[1]}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def claim_final_oos(
    *,
    manifest_path: str | Path,
    experiment: AlphaExperiment,
    experiment_artifact_sha256: str,
    database: ProjectDatabase | None = None,
) -> Path:
    """Consume a non-overlapping range before the runner opens its observations.

    Discovered sibling receipts are imported without rewriting them. Undiscovered
    legacy receipt directories are not proof of an untouched range. Database or
    receipt export failure never falls back to a new, directory-local claim.
    """

    manifest = Path(manifest_path).resolve()
    registry = manifest.parent / ".alpha_consumed"
    registry.mkdir(parents=True, exist_ok=True)
    holdout_id = final_oos_identity(experiment)
    receipt = registry / f"{holdout_id}.json"
    payload = {
        "schema_version": 2,
        "registry_scope": "canonical_project_database",
        "claim_id": str(uuid.uuid4()),
        "status": "started",
        "claimed_at": datetime.now(UTC).isoformat(),
        "holdout_identity": holdout_id,
        "experiment_id": experiment.experiment_id,
        "experiment_fingerprint": experiment.fingerprint(),
        "experiment_artifact_sha256": str(experiment_artifact_sha256).strip().lower(),
        "dataset_manifest_sha256": experiment.dataset_manifest_sha256,
        "git_sha": experiment.git_sha,
        "final_oos_range": list(experiment.final_oos_range),
    }
    legacy = _local_receipts(registry, experiment.dataset_manifest_sha256)
    with _locked_claims(database or ProjectDatabase(), experiment.dataset_manifest_sha256) as claims:
        for key, item in legacy.items():
            claims.setdefault(key, item)
        start, end = experiment.final_oos_range
        consumed = any(start <= item["final_oos_range"][1] and end >= item["final_oos_range"][0]
                       for item in claims.values())
        if not consumed:
            claims[holdout_id] = payload
    # Commit imported legacy evidence even when the requested claim is rejected.
    if consumed:
        raise FinalOOSAlreadyConsumed("final OOS was already consumed for an overlapping dataset range")
    # The durable claim precedes export. An export failure remains consumed.
    try:
        with receipt.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
    except FileExistsError as exc:
        raise FinalOOSAlreadyConsumed(
            "final OOS was already consumed for this dataset and holdout range"
        ) from exc
    return receipt


def complete_final_oos(
    receipt_path: str | Path,
    *,
    verdict: str,
    report_path: str | Path,
    report_sha256: str,
    database: ProjectDatabase | None = None,
) -> None:
    """Mark an existing one-shot claim complete without creating a new claim."""

    receipt = Path(receipt_path)
    payload = _load_receipt(receipt)
    if payload.get("status") != "started":
        raise ValueError("final OOS receipt is not in started state")
    payload.update(
        {
            "status": "completed",
            "completed_at": datetime.now(UTC).isoformat(),
            "verdict": str(verdict),
            "report_path": str(Path(report_path).resolve()),
            "report_sha256": str(report_sha256).strip().lower(),
        }
    )
    legacy = _local_receipts(receipt.parent, payload["dataset_manifest_sha256"])
    with _locked_claims(database or ProjectDatabase(), payload["dataset_manifest_sha256"]) as claims:
        for key, item in legacy.items():
            claims.setdefault(key, item)
        current = claims.get(payload["holdout_identity"])
        if not current or current.get("status") != "started":
            raise ValueError("canonical final OOS claim is not in started state")
        if (current.get("claim_id") != payload.get("claim_id")
                or current.get("experiment_artifact_sha256") != payload.get("experiment_artifact_sha256")):
            raise ValueError("receipt does not match canonical final OOS claim")
        claims[payload["holdout_identity"]] = payload
    temp = receipt.with_suffix(receipt.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(receipt)


def _load_receipt(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") not in (1, 2):
        raise ValueError("invalid final OOS consumption receipt")
    _validate_claim(payload)
    return payload


def _validate_claim(payload: dict[str, Any]) -> None:
    digest = payload.get("dataset_manifest_sha256", "")
    window = payload.get("final_oos_range")
    if (not isinstance(digest, str) or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
            or not isinstance(window, list) or len(window) != 2
            or any(type(value) is not int for value in window)
            or not 0 < window[0] <= window[1]
            or payload.get("status") not in ("started", "completed")):
        raise ValueError("invalid final OOS claim provenance")
    identity = hashlib.sha256(f"{digest}:{window[0]}:{window[1]}".encode()).hexdigest()
    if payload.get("holdout_identity") != identity:
        raise ValueError("invalid final OOS claim identity")


def _local_receipts(directory: Path, digest: str) -> dict[str, dict[str, Any]]:
    claims = {}
    for path in sorted(directory.glob("*.json")):
        payload = _load_receipt(path)
        if payload["dataset_manifest_sha256"] == digest:
            claims[payload["holdout_identity"]] = payload
    return claims


@contextmanager
def _locked_claims(database: ProjectDatabase, digest: str) -> Iterator[dict[str, Any]]:
    """Serialize all ranges of one dataset, including first-claim races.

    SQLite uses BEGIN IMMEDIATE. PostgreSQL's conflict-safe seed insert and row
    lock also serialize the initially absent row; optimistic read/put alone
    would not protect that case. No additional database or schema is created.
    """
    database.initialize()
    with database.connect() as connection:
        try:
            database._begin(connection, immediate=True)
            database._execute(connection, """
                INSERT INTO project_kv(namespace, item_key, value_json, version, updated_at_ms)
                VALUES (?, ?, ?, 1, ?) ON CONFLICT(namespace, item_key) DO NOTHING
            """, (_NAMESPACE, digest, '{"schema_version":2,"claims":{}}', int(time.time() * 1000)))
            row = database._fetchone(connection, """
                SELECT value_json, version FROM project_kv WHERE namespace = ? AND item_key = ?
            """, (_NAMESPACE, digest), lock=True)
            record = json.loads(row["value_json"])
            if record.get("schema_version") != 2 or not isinstance(record.get("claims"), dict):
                raise ValueError("invalid canonical final OOS registry")
            claims = record["claims"]
            for key, item in claims.items():
                _validate_claim(item)
                if item["dataset_manifest_sha256"] != digest or item["holdout_identity"] != key:
                    raise ValueError("canonical final OOS registry identity mismatch")
            yield claims
            database._execute(connection, """
                UPDATE project_kv SET value_json = ?, version = ?, updated_at_ms = ?
                WHERE namespace = ? AND item_key = ?
            """, (json.dumps(record, allow_nan=False), row["version"] + 1,
                  int(time.time() * 1000), _NAMESPACE, digest))
            connection.commit()
        except Exception:
            connection.rollback()
            raise


__all__ = [
    "FinalOOSAlreadyConsumed",
    "claim_final_oos",
    "complete_final_oos",
    "final_oos_identity",
]
