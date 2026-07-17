"""Fail-closed strategy promotion evaluation.

The engine produces an auditable report only.  A positive automated report still
requires a manual decision in :mod:`experiments.registry`; it never changes
execution flags, credentials, capital or deployment state.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any, Mapping

from exchange_connector.execution_contract import MAINNET_EXECUTION_COMPILED


class PromotionTarget(StrEnum):
    PAPER = "paper"
    TESTNET = "testnet"
    CONTROLLED_MAINNET = "controlled_mainnet"


@dataclass(frozen=True, slots=True)
class PromotionPolicy:
    minimum_walk_forward_windows: int = 6
    minimum_profitable_window_percent: float = 60.0
    maximum_drawdown_percent: float = 10.0
    minimum_benchmarks_beaten: int = 2
    maximum_positive_window_concentration_percent: float = 40.0
    minimum_paper_testnet_matches: int = 20
    maximum_p95_latency_divergence_ms: float = 2_000.0
    maximum_p95_slippage_divergence_bps: float = 15.0
    maximum_partial_fill_rate_percent: float = 20.0
    maximum_fill_ratio_delta: float = 0.10


@dataclass(frozen=True, slots=True)
class PromotionGateReport:
    experiment_id: str
    target_stage: str
    status: str
    automated_gate_passed: bool
    eligible_for_manual_approval: bool
    manual_approval_required: bool
    passed_gates: tuple[str, ...]
    failed_gates: tuple[str, ...]
    warnings: tuple[str, ...]
    metrics: dict[str, Any]
    policy: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PromotionGateEngine:
    """Evaluate research, paper and Testnet evidence without side effects."""

    def __init__(self, policy: PromotionPolicy | None = None) -> None:
        self.policy = policy or PromotionPolicy()

    def evaluate(
        self,
        experiment: Mapping[str, Any],
        *,
        target_stage: PromotionTarget | str,
        paper_testnet_validation: Mapping[str, Any] | None = None,
        reconciliation: Mapping[str, Any] | None = None,
        private_stream: Mapping[str, Any] | None = None,
    ) -> PromotionGateReport:
        target = PromotionTarget(str(target_stage).strip().lower())
        experiment_id = _identifier(experiment.get("experiment_id"), "experiment_id")
        passed: list[str] = []
        failed: list[str] = []
        warnings: list[str] = []
        metrics: dict[str, Any] = {}

        self._research_gates(experiment, passed=passed, failed=failed, metrics=metrics)

        if target in {PromotionTarget.TESTNET, PromotionTarget.CONTROLLED_MAINNET}:
            self._paper_to_testnet_gates(
                experiment,
                validation=paper_testnet_validation or {},
                reconciliation=reconciliation or {},
                private_stream=private_stream or {},
                passed=passed,
                failed=failed,
                metrics=metrics,
            )

        if target is PromotionTarget.CONTROLLED_MAINNET:
            if MAINNET_EXECUTION_COMPILED:
                passed.append("mainnet_execution_build_available")
            else:
                failed.append("mainnet_execution_compiled_out")
            warnings.append(
                "controlled Mainnet additionally requires a new audited release, "
                "limited subaccount and expiring owner approval"
            )

        automated = not failed
        return PromotionGateReport(
            experiment_id=experiment_id,
            target_stage=target.value,
            status="eligible_for_manual_approval" if automated else "blocked",
            automated_gate_passed=automated,
            eligible_for_manual_approval=automated,
            manual_approval_required=True,
            passed_gates=tuple(passed),
            failed_gates=tuple(failed),
            warnings=tuple(warnings),
            metrics=metrics,
            policy=asdict(self.policy),
        )

    def _research_gates(
        self,
        experiment: Mapping[str, Any],
        *,
        passed: list[str],
        failed: list[str],
        metrics: dict[str, Any],
    ) -> None:
        if str(experiment.get("status")) in {
            "completed",
            "promotion_pending",
            "promoted",
            "rejected",
        }:
            passed.append("experiment_completed")
        else:
            failed.append("experiment_not_completed")

        commit_sha = str(experiment.get("commit_sha", ""))
        if 7 <= len(commit_sha) <= 64 and all(char in "0123456789abcdefABCDEF" for char in commit_sha):
            passed.append("source_commit_recorded")
        else:
            failed.append("source_commit_invalid")

        manifest = _mapping(experiment.get("manifest"))
        if manifest.get("manifest_id") and manifest.get("version"):
            passed.append("versioned_manifest_recorded")
        else:
            failed.append("versioned_manifest_missing")
        if bool(manifest.get("validated")):
            passed.append("historical_manifest_validated")
        else:
            failed.append("historical_manifest_not_validated")

        results = _mapping(experiment.get("results"))
        walk = _mapping(results.get("walk_forward"))
        benchmarks = _mapping(results.get("benchmarks"))
        data_quality = _mapping(results.get("data_validation"))

        windows = walk.get("windows")
        window_count = len(windows) if isinstance(windows, list) else int(_number(walk.get("window_count")))
        profitable_percent = _number(walk.get("profitable_window_percent"))
        net_pnl = _number(walk.get("net_pnl"))
        max_drawdown = _number(walk.get("max_drawdown_percent"))
        sharpe = _number(walk.get("sharpe_ratio"))
        sortino = _number(walk.get("sortino_ratio"))
        concentration = _positive_window_concentration(walk)
        metrics.update(
            {
                "walk_forward_window_count": window_count,
                "profitable_window_percent": profitable_percent,
                "oos_net_pnl": net_pnl,
                "max_drawdown_percent": max_drawdown,
                "sharpe_ratio": sharpe,
                "sortino_ratio": sortino,
                "positive_window_concentration_percent": concentration,
            }
        )

        _threshold(
            window_count >= self.policy.minimum_walk_forward_windows,
            "minimum_walk_forward_windows",
            passed,
            failed,
        )
        _threshold(
            profitable_percent >= self.policy.minimum_profitable_window_percent,
            "profitable_window_ratio",
            passed,
            failed,
        )
        _threshold(net_pnl > 0.0, "positive_oos_net_pnl", passed, failed)
        _threshold(
            0.0 <= max_drawdown <= self.policy.maximum_drawdown_percent,
            "drawdown_within_policy",
            passed,
            failed,
        )
        _threshold(max(sharpe, sortino) > 0.0, "positive_risk_adjusted_score", passed, failed)
        _threshold(
            concentration <= self.policy.maximum_positive_window_concentration_percent,
            "oos_profit_not_concentrated",
            passed,
            failed,
        )

        benchmark_metadata = _mapping(benchmarks.get("metadata"))
        candidate_name = str(
            benchmark_metadata.get("candidate_name")
            or benchmarks.get("candidate_name")
            or "candidate"
        )
        ranking = [str(item) for item in benchmarks.get("ranking", [])] if isinstance(
            benchmarks.get("ranking"), list
        ) else []
        required = {"buy_and_hold", "trend_following", "breakout", "mean_reversion"}
        present = required.issubset(set(ranking))
        candidate_present = candidate_name in ranking
        beats_buy_hold = bool(benchmark_metadata.get("candidate_beats_buy_hold"))
        beaten = _benchmarks_beaten(ranking, candidate_name, required)
        metrics.update(
            {
                "candidate_name": candidate_name,
                "benchmark_ranking": ranking,
                "benchmarks_beaten": beaten,
                "candidate_beats_buy_hold": beats_buy_hold,
            }
        )
        _threshold(present, "mandatory_benchmarks_present", passed, failed)
        _threshold(candidate_present, "candidate_present_in_benchmark_table", passed, failed)
        _threshold(beats_buy_hold, "candidate_beats_buy_and_hold", passed, failed)
        _threshold(
            beaten >= self.policy.minimum_benchmarks_beaten,
            "candidate_beats_required_benchmark_count",
            passed,
            failed,
        )

        if data_quality:
            valid = bool(data_quality.get("valid", data_quality.get("status") == "ok"))
            material_warnings = list(data_quality.get("material_warnings") or [])
            _threshold(valid, "historical_data_validation_passed", passed, failed)
            _threshold(not material_warnings, "no_material_data_warnings", passed, failed)
        else:
            failed.append("historical_data_validation_result_missing")

        metadata = _mapping(walk.get("metadata"))
        for field, gate in (
            ("lookahead_allowed", "lookahead_disabled"),
            ("fees_included", "fees_included"),
            ("slippage_included", "slippage_included"),
            ("market_impact_included", "market_impact_included"),
            ("funding_included", "funding_included"),
        ):
            expected = False if field == "lookahead_allowed" else True
            _threshold(metadata.get(field) is expected, gate, passed, failed)

    def _paper_to_testnet_gates(
        self,
        experiment: Mapping[str, Any],
        *,
        validation: Mapping[str, Any],
        reconciliation: Mapping[str, Any],
        private_stream: Mapping[str, Any],
        passed: list[str],
        failed: list[str],
        metrics: dict[str, Any],
    ) -> None:
        matched = int(_number(validation.get("matched_count")))
        unmatched_paper = int(_number(validation.get("unmatched_paper_count")))
        unmatched_testnet = int(_number(validation.get("unmatched_testnet_count")))
        p95_latency = _number(validation.get("p95_latency_divergence_ms"))
        p95_slippage = _number(validation.get("p95_slippage_divergence_bps"))
        partial_rate = _number(validation.get("testnet_partial_fill_rate_percent"))
        fill_ratio_delta = _number(validation.get("maximum_fill_ratio_delta"))
        metrics.update(
            {
                "paper_testnet_matched_count": matched,
                "paper_unmatched_count": unmatched_paper,
                "testnet_unmatched_count": unmatched_testnet,
                "p95_latency_divergence_ms": p95_latency,
                "p95_slippage_divergence_bps": p95_slippage,
                "testnet_partial_fill_rate_percent": partial_rate,
                "maximum_fill_ratio_delta": fill_ratio_delta,
            }
        )
        _threshold(
            bool(validation.get("promotion_eligible")),
            "paper_testnet_validation_eligible",
            passed,
            failed,
        )
        _threshold(
            matched >= self.policy.minimum_paper_testnet_matches,
            "minimum_paper_testnet_matches",
            passed,
            failed,
        )
        _threshold(
            unmatched_paper == 0 and unmatched_testnet == 0,
            "all_fill_pairs_resolved",
            passed,
            failed,
        )
        _threshold(
            p95_latency <= self.policy.maximum_p95_latency_divergence_ms,
            "latency_divergence_within_policy",
            passed,
            failed,
        )
        _threshold(
            p95_slippage <= self.policy.maximum_p95_slippage_divergence_bps,
            "slippage_divergence_within_policy",
            passed,
            failed,
        )
        _threshold(
            partial_rate <= self.policy.maximum_partial_fill_rate_percent,
            "partial_fill_rate_within_policy",
            passed,
            failed,
        )
        _threshold(
            fill_ratio_delta <= self.policy.maximum_fill_ratio_delta,
            "fill_ratio_divergence_within_policy",
            passed,
            failed,
        )

        _threshold(
            bool(reconciliation.get("restart_safe")),
            "startup_reconciliation_safe",
            passed,
            failed,
        )
        _threshold(
            bool(private_stream.get("ready")),
            "private_order_stream_ready",
            passed,
            failed,
        )
        results = _mapping(experiment.get("results"))
        paper = _mapping(results.get("paper_summary"))
        _threshold(
            int(_number(paper.get("hard_risk_breaches"))) == 0,
            "paper_has_no_hard_risk_breach",
            passed,
            failed,
        )
        _threshold(
            int(_number(paper.get("unresolved_execution_intents"))) == 0,
            "paper_has_no_unresolved_execution_intents",
            passed,
            failed,
        )


def _threshold(condition: bool, name: str, passed: list[str], failed: list[str]) -> None:
    (passed if condition else failed).append(name)


def _positive_window_concentration(walk: Mapping[str, Any]) -> float:
    explicit = walk.get("positive_window_concentration_percent")
    if explicit is not None:
        return _number(explicit)
    windows = walk.get("windows")
    if not isinstance(windows, list):
        return 100.0
    positives: list[float] = []
    for window in windows:
        if not isinstance(window, Mapping):
            continue
        result = _mapping(window.get("result"))
        pnl = _number(result.get("net_pnl", window.get("net_pnl")))
        if pnl > 0:
            positives.append(pnl)
    total = sum(positives)
    return max(positives) / total * 100.0 if total > 0 else 100.0


def _benchmarks_beaten(ranking: list[str], candidate: str, required: set[str]) -> int:
    if candidate not in ranking:
        return 0
    position = ranking.index(candidate)
    return sum(1 for name in required if name in ranking and position < ranking.index(name))


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _number(value: Any) -> float:
    try:
        parsed = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return parsed if math.isfinite(parsed) else 0.0


def _identifier(value: Any, name: str) -> str:
    clean = str(value or "").strip()
    if not clean or len(clean) > 200:
        raise ValueError(f"{name} must contain 1..200 characters")
    return clean


__all__ = [
    "PromotionGateEngine",
    "PromotionGateReport",
    "PromotionPolicy",
    "PromotionTarget",
]
