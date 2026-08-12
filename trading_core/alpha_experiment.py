"""Immutable pre-registration contract for cost-adjusted alpha validation."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping

_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True, slots=True)
class AlphaExperiment:
    experiment_id: str
    git_sha: str
    dataset_manifest_sha256: str
    strategy: str
    parameters: dict[str, object]
    cost_config: dict[str, object]
    risk_config: dict[str, object]
    execution_timing: str
    train_range: tuple[int, int]
    validation_ranges: tuple[tuple[int, int], ...]
    final_oos_range: tuple[int, int]
    benchmarks: tuple[str, ...]
    acceptance_metrics: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.experiment_id.strip() or not self.strategy.strip():
            raise ValueError("experiment identity and strategy are required")
        if not _GIT_SHA.fullmatch(self.git_sha):
            raise ValueError("git_sha must be 40 lowercase hex characters")
        if not _HEX_SHA256.fullmatch(self.dataset_manifest_sha256):
            raise ValueError("dataset_manifest_sha256 must be 64 lowercase hex characters")
        if not self.parameters or not self.cost_config or not self.risk_config:
            raise ValueError("strategy parameters, cost config and risk config are required")
        if self.execution_timing not in {"auto", "next_event", "same_event"}:
            raise ValueError("unsupported execution timing")
        if self.execution_timing == "same_event":
            raise ValueError("final alpha experiments must not use same_event timing")
        if not self.validation_ranges or not self.benchmarks or not self.acceptance_metrics:
            raise ValueError("validation ranges, benchmarks and acceptance metrics are required")
        if len(set(self.benchmarks)) != len(self.benchmarks):
            raise ValueError("benchmarks must be unique")
        if len(set(self.acceptance_metrics)) != len(self.acceptance_metrics):
            raise ValueError("acceptance metrics must be unique")

        ranges = (self.train_range, *self.validation_ranges, self.final_oos_range)
        if any(start <= 0 or end < start for start, end in ranges):
            raise ValueError("experiment ranges must be positive and ordered")
        if tuple(sorted(ranges, key=lambda item: item[0])) != ranges:
            raise ValueError("train, validation and final OOS ranges must be chronological")
        for previous, current in zip(ranges, ranges[1:]):
            if current[0] <= previous[1]:
                raise ValueError("train, validation and final OOS ranges must not overlap")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "AlphaExperiment":
        if not isinstance(payload, Mapping):
            raise TypeError("alpha experiment payload must be a mapping")
        try:
            return cls(
                experiment_id=str(payload["experiment_id"]).strip(),
                git_sha=str(payload["git_sha"]).strip().lower(),
                dataset_manifest_sha256=str(payload["dataset_manifest_sha256"]).strip().lower(),
                strategy=str(payload["strategy"]).strip(),
                parameters=dict(payload["parameters"]),
                cost_config=dict(payload["cost_config"]),
                risk_config=dict(payload["risk_config"]),
                execution_timing=str(payload["execution_timing"]).strip(),
                train_range=_range(payload["train_range"], "train_range"),
                validation_ranges=tuple(
                    _range(item, "validation_range") for item in payload["validation_ranges"]
                ),
                final_oos_range=_range(payload["final_oos_range"], "final_oos_range"),
                benchmarks=tuple(str(item).strip() for item in payload["benchmarks"]),
                acceptance_metrics=tuple(
                    str(item).strip() for item in payload["acceptance_metrics"]
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, ValueError) and str(exc).startswith((
                "git_sha",
                "dataset_manifest",
                "experiment",
                "strategy",
                "benchmarks",
                "acceptance",
                "train",
            )):
                raise
            raise ValueError(f"invalid alpha experiment: {exc}") from exc

    @classmethod
    def load(cls, path: str | Path) -> "AlphaExperiment":
        source = Path(path)
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise
        except Exception as exc:
            raise ValueError(f"cannot read alpha experiment {source}: {exc}") from exc
        if not isinstance(payload, Mapping) or int(payload.get("schema_version", 0)) != 1:
            raise ValueError("unsupported alpha experiment artifact schema")
        experiment_payload = payload.get("experiment")
        if not isinstance(experiment_payload, Mapping):
            raise ValueError("alpha experiment artifact is missing experiment payload")
        experiment = cls.from_dict(experiment_payload)
        expected = str(payload.get("fingerprint") or "").strip().lower()
        if expected != experiment.fingerprint():
            raise ValueError("alpha experiment fingerprint mismatch")
        return experiment

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def canonical_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    def fingerprint(self) -> str:
        return sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def artifact_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "experiment": self.to_dict(),
            "fingerprint": self.fingerprint(),
        }

    def save(self, path: str | Path) -> None:
        """Persist once; preregistrations are immutable by construction."""

        target = Path(path)
        if target.exists():
            raise FileExistsError("alpha preregistration is immutable; choose a new experiment id")
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_suffix(target.suffix + ".tmp")
        temp.write_text(
            json.dumps(self.artifact_dict(), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temp.replace(target)


def _range(value: Any, name: str) -> tuple[int, int]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"{name} must contain exactly two timestamps")
    try:
        start, end = int(value[0]), int(value[1])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} timestamps must be integers") from exc
    return start, end


__all__ = ["AlphaExperiment"]
