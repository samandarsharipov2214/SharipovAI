"""Automatic, reproducible walk-forward and benchmark experiment execution."""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any, Callable, Mapping

from historical_data import HistoricalDataLoader
from storage import ProjectDatabase
from trading_core import (
    BacktestConfig,
    Strategy,
    WalkForwardBacktester,
    WalkForwardConfig,
    compare_strategy_to_benchmarks,
)

from .adapters import manifest_for_experiment
from .registry import ExperimentRegistry

_RESULT_NAMESPACE = "research_experiment_immutable_results"


@dataclass(frozen=True, slots=True)
class AutomaticExperimentRequest:
    commit_sha: str
    strategy_name: str
    strategy_config: Mapping[str, Any]
    backtest_config: BacktestConfig
    walk_forward_config: WalkForwardConfig
    manifest_path: str
    dataset_root: str | None = None
    event_limit: int | None = None
    metadata: Mapping[str, Any] | None = None


class ImmutableExperimentResultStore:
    """Write-once result evidence addressed by experiment and result name."""

    def __init__(self, database: ProjectDatabase | None = None) -> None:
        self.database = database or ProjectDatabase()
        self.database.initialize()

    def save(self, experiment_id: str, result_name: str, result: Any) -> dict[str, Any]:
        clean_experiment = _identifier(experiment_id, "experiment_id")
        clean_name = _identifier(result_name, "result_name")
        payload = _jsonable(result)
        digest = _digest(payload)
        key = f"{clean_experiment}:{clean_name}"
        document = {
            "experiment_id": clean_experiment,
            "result_name": clean_name,
            "sha256": digest,
            "result": payload,
            "stored_at_ms": int(time.time() * 1000),
            "immutable": True,
        }
        self.database.put_json(_RESULT_NAMESPACE, key, document, expected_version=0)
        return document

    def get(self, experiment_id: str, result_name: str) -> dict[str, Any] | None:
        key = f"{_identifier(experiment_id, 'experiment_id')}:{_identifier(result_name, 'result_name')}"
        current = self.database.get_json(_RESULT_NAMESPACE, key)
        if current is None:
            return None
        return {**dict(current["value"]), "version": int(current["version"])}


class AutomaticExperimentRunner:
    """Create, execute, persist and complete one deterministic experiment."""

    def __init__(
        self,
        *,
        database: ProjectDatabase | None = None,
        registry: ExperimentRegistry | None = None,
        result_store: ImmutableExperimentResultStore | None = None,
    ) -> None:
        self.database = database or ProjectDatabase()
        self.database.initialize()
        self.registry = registry or ExperimentRegistry(self.database)
        self.result_store = result_store or ImmutableExperimentResultStore(self.database)

    def run(
        self,
        request: AutomaticExperimentRequest,
        *,
        walk_forward_strategy_factory: Callable[[tuple[Any, ...], int], Strategy],
        benchmark_strategy_factory: Callable[[], Strategy],
        actor: str = "automatic-experiment-runner",
    ) -> dict[str, Any]:
        started_at_ms = int(time.time() * 1000)
        with HistoricalDataLoader(
            request.manifest_path,
            dataset_root=request.dataset_root,
            validate_on_open=True,
        ) as loader:
            validation = loader.validation_report or loader.validate()
            if not validation.valid:
                raise ValueError("historical data validation did not pass")
            manifest_identity = manifest_for_experiment(
                loader.manifest,
                validated=True,
                validation_report_id=f"dataset:{loader.manifest.dataset_id}:{loader.manifest.dataset_version}",
            )
            events = tuple(loader.iter_events(limit=request.event_limit))
            if not events:
                raise ValueError("automatic experiment has no market events")

            identity_payload = {
                "commit_sha": request.commit_sha,
                "manifest": manifest_identity,
                "strategy_name": request.strategy_name,
                "strategy_config": _jsonable(request.strategy_config),
                "backtest_config": _jsonable(request.backtest_config),
                "walk_forward_config": _jsonable(request.walk_forward_config),
            }
            experiment_id = "exp_" + _digest(identity_payload)[:32]
            if self.registry.get(experiment_id) is not None:
                raise RuntimeError(
                    "an experiment with the same immutable commit/manifest/config fingerprint already exists"
                )
            created = self.registry.create(
                experiment_id=experiment_id,
                commit_sha=request.commit_sha,
                manifest=manifest_identity,
                strategy_name=request.strategy_name,
                strategy_config=request.strategy_config,
                backtest_config={
                    **_jsonable(request.backtest_config),
                    "walk_forward": _jsonable(request.walk_forward_config),
                },
                metadata={
                    **_jsonable(request.metadata or {}),
                    "runner": "AutomaticExperimentRunner",
                    "event_count": len(events),
                    "run_fingerprint": _digest(identity_payload),
                },
                created_at_ms=started_at_ms,
            )

            current = created
            try:
                data_result = _data_validation_result(validation)
                current = self._persist_result(
                    experiment_id,
                    "data_validation",
                    data_result,
                    actor=actor,
                    expected_version=current["version"],
                )

                walk_result = WalkForwardBacktester(
                    request.backtest_config,
                    request.walk_forward_config,
                ).run(events, walk_forward_strategy_factory)
                walk_payload = _walk_forward_result(walk_result, request.backtest_config)
                current = self._persist_result(
                    experiment_id,
                    "walk_forward",
                    walk_payload,
                    actor=actor,
                    expected_version=current["version"],
                )

                benchmark_result = compare_strategy_to_benchmarks(
                    events,
                    benchmark_strategy_factory,
                    candidate_name=request.strategy_name,
                    config=request.backtest_config,
                )
                benchmark_payload = _jsonable(benchmark_result)
                current = self._persist_result(
                    experiment_id,
                    "benchmarks",
                    benchmark_payload,
                    actor=actor,
                    expected_version=current["version"],
                )

                finished_at_ms = int(time.time() * 1000)
                summary = {
                    "experiment_id": experiment_id,
                    "started_at_ms": started_at_ms,
                    "finished_at_ms": finished_at_ms,
                    "duration_ms": max(0, finished_at_ms - started_at_ms),
                    "event_count": len(events),
                    "walk_forward_windows": len(walk_result.windows),
                    "benchmark_count": len(benchmark_result.entries),
                    "immutable_result_names": [
                        "data_validation",
                        "walk_forward",
                        "benchmarks",
                    ],
                    "all_costs_included": True,
                    "lookahead_allowed": False,
                }
                current = self._persist_result(
                    experiment_id,
                    "run_summary",
                    summary,
                    actor=actor,
                    expected_version=current["version"],
                )
                completed = self.registry.complete(
                    experiment_id,
                    actor=actor,
                    expected_version=current["version"],
                    updated_at_ms=finished_at_ms,
                )
                return completed
            except Exception as exc:
                latest = self.registry.get(experiment_id)
                if latest is not None and latest.get("status") in {"created", "running"}:
                    try:
                        self.registry.set_status(
                            experiment_id,
                            "failed",
                            actor=actor,
                            note=f"{type(exc).__name__}: {exc}"[:2_000],
                            expected_version=latest["version"],
                        )
                    except Exception:
                        pass
                raise

    def _persist_result(
        self,
        experiment_id: str,
        name: str,
        result: Any,
        *,
        actor: str,
        expected_version: int,
    ) -> dict[str, Any]:
        immutable = self.result_store.save(experiment_id, name, result)
        return self.registry.record_result(
            experiment_id,
            name,
            {
                **_jsonable(result),
                "immutable_sha256": immutable["sha256"],
                "immutable_namespace": _RESULT_NAMESPACE,
            },
            actor=actor,
            expected_version=expected_version,
        )


def _walk_forward_result(result: Any, config: BacktestConfig) -> dict[str, Any]:
    payload = _jsonable(result)
    windows = payload.get("windows") if isinstance(payload, dict) else []
    window_results = [
        item.get("result", {})
        for item in windows
        if isinstance(item, Mapping) and isinstance(item.get("result"), Mapping)
    ]
    payload["window_count"] = len(window_results)
    payload["sharpe_ratio"] = _mean(
        float(item.get("sharpe_ratio", 0.0) or 0.0) for item in window_results
    )
    payload["sortino_ratio"] = _mean(
        float(item.get("sortino_ratio", 0.0) or 0.0) for item in window_results
    )
    metadata = dict(payload.get("metadata") or {})
    metadata.update(
        {
            "lookahead_allowed": False,
            "fees_included": True,
            "slippage_included": True,
            "market_impact_included": True,
            "funding_included": True,
            "maker_fee_rate": config.maker_fee_rate,
            "taker_fee_rate": config.fee_rate,
            "slippage_bps": config.slippage_bps,
            "market_impact_bps": config.market_impact_bps,
        }
    )
    payload["metadata"] = metadata
    return payload


def _data_validation_result(report: Any) -> dict[str, Any]:
    payload = _jsonable(report)
    issues = payload.get("issues", []) if isinstance(payload, dict) else []
    material = [
        item
        for item in issues
        if isinstance(item, Mapping) and str(item.get("severity", "error")) == "error"
    ]
    return {
        **payload,
        "valid": bool(getattr(report, "valid", False)),
        "material_warnings": material,
    }


def _jsonable(value: Any) -> Any:
    if hasattr(value, "to_dict") and callable(value.to_dict):
        value = value.to_dict()
    elif is_dataclass(value):
        value = asdict(value)
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True))


def _digest(value: Any) -> str:
    encoded = json.dumps(
        _jsonable(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _identifier(value: Any, name: str) -> str:
    clean = str(value or "").strip()
    if not clean or len(clean) > 200:
        raise ValueError(f"invalid {name}")
    if any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.:-" for character in clean):
        raise ValueError(f"invalid {name}")
    return clean


def _mean(values: Any) -> float:
    numbers = list(values)
    return round(sum(numbers) / len(numbers), 8) if numbers else 0.0


__all__ = [
    "AutomaticExperimentRequest",
    "AutomaticExperimentRunner",
    "ImmutableExperimentResultStore",
]
