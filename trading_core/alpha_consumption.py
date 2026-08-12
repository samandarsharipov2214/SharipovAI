"""Atomic one-shot consumption receipts for untouched final-OOS experiments."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .alpha_experiment import AlphaExperiment


class FinalOOSAlreadyConsumed(RuntimeError):
    """Raised when an experiment fingerprint has already opened final OOS."""


def claim_final_oos(
    *,
    manifest_path: str | Path,
    experiment: AlphaExperiment,
    experiment_artifact_sha256: str,
) -> Path:
    """Atomically consume final OOS for this experiment fingerprint.

    The receipt lives beside the canonical dataset manifest rather than beside a
    caller-selected result path. Copying/renaming the experiment file therefore
    does not create a second legitimate look at the same dataset holdout.
    """

    manifest = Path(manifest_path).resolve()
    registry = manifest.parent / ".alpha_consumed"
    registry.mkdir(parents=True, exist_ok=True)
    receipt = registry / f"{experiment.fingerprint()}.json"
    payload = {
        "schema_version": 1,
        "status": "started",
        "claimed_at": datetime.now(UTC).isoformat(),
        "experiment_id": experiment.experiment_id,
        "experiment_fingerprint": experiment.fingerprint(),
        "experiment_artifact_sha256": str(experiment_artifact_sha256).strip().lower(),
        "dataset_manifest_sha256": experiment.dataset_manifest_sha256,
        "git_sha": experiment.git_sha,
        "final_oos_range": list(experiment.final_oos_range),
    }
    try:
        with receipt.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
    except FileExistsError as exc:
        raise FinalOOSAlreadyConsumed(
            "final OOS was already consumed for this experiment fingerprint"
        ) from exc
    return receipt


def complete_final_oos(
    receipt_path: str | Path,
    *,
    verdict: str,
    report_path: str | Path,
    report_sha256: str,
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
    temp = receipt.with_suffix(receipt.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(receipt)


def _load_receipt(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or int(payload.get("schema_version", 0)) != 1:
        raise ValueError("invalid final OOS consumption receipt")
    return payload


__all__ = ["FinalOOSAlreadyConsumed", "claim_final_oos", "complete_final_oos"]
