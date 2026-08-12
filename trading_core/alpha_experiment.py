"""Immutable pre-registration contract for cost-adjusted alpha validation."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json


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
        if not self.experiment_id or not self.git_sha or len(self.dataset_manifest_sha256) != 64:
            raise ValueError("experiment identity, git SHA and manifest SHA256 are required")
        if self.execution_timing not in {"auto", "next_event", "same_event"}:
            raise ValueError("unsupported execution timing")
        if self.execution_timing == "same_event":
            raise ValueError("final alpha experiments must not use same_event timing")
        if not self.validation_ranges or not self.benchmarks or not self.acceptance_metrics:
            raise ValueError("validation ranges, benchmarks and acceptance metrics are required")
        ranges = (self.train_range, *self.validation_ranges, self.final_oos_range)
        if any(start <= 0 or end < start for start, end in ranges):
            raise ValueError("experiment ranges must be positive and ordered")
        if self.final_oos_range[0] <= max(end for _, end in (self.train_range, *self.validation_ranges)):
            raise ValueError("final OOS must begin after all training and validation ranges")

    def canonical_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))

    def fingerprint(self) -> str:
        return sha256(self.canonical_json().encode("utf-8")).hexdigest()


__all__ = ["AlphaExperiment"]
