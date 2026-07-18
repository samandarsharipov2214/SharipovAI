"""Immutable Phase 8 analysis for bounded Testnet campaign evidence.

The analyzer is read-only with respect to execution. It consumes canonical campaign,
private execution and final-report evidence, then persists an immutable operational
assessment and a non-binding promotion recommendation.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import statistics
import time
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from storage import ProjectDatabase, list_json_items

from .core import FinalPromotionReportEngine, TestnetShadowCampaign
from .phase7_monitor import Phase7CampaignMonitor

_ANALYSIS_NAMESPACE = "phase8_campaign_analysis"
_EVENT_NAMESPACE = "phase8_campaign_analysis_events"
_TERMINAL = {"completed", "blocked", "cancelled"}


@dataclass(frozen=True, slots=True)
class Phase8AnalysisPolicy:
    minimum_actual_private_fills: int = 20
    maximum_execution_cost_drawdown_percent: float = 0.35
    maximum_actual_fee_bps: float = 20.0
    maximum_p95_slippage_bps: float = 15.0
    maximum_p95_latency_ms: float = 2_000.0
    maximum_partial_fill_rate_percent: float = 20.0

    @classmethod
    def from_environment(cls) -> "Phase8AnalysisPolicy":
        return cls(
            minimum_actual_private_fills=_bounded_int("PHASE8_MIN_ACTUAL_PRIVATE_FILLS", 20, 20, 10_000),
            maximum_execution_cost_drawdown_percent=_bounded_float(
                "PHASE8_MAX_EXECUTION_COST_DRAWDOWN_PERCENT", 0.35, 0.01, 10.0
            ),
            maximum_actual_fee_bps=_bounded_float("PHASE8_MAX_ACTUAL_FEE_BPS", 20.0, 0.1, 500.0),
            maximum_p95_slippage_bps=_bounded_float("PHASE8_MAX_P95_SLIPPAGE_BPS", 15.0, 0.1, 500.0),
            maximum_p95_latency_ms=_bounded_float("PHASE8_MAX_P95_LATENCY_MS", 2_000.0, 10.0, 120_000.0),
            maximum_partial_fill_rate_percent=_bounded_float(
                "PHASE8_MAX_PARTIAL_FILL_RATE_PERCENT", 20.0, 0.0, 100.0
            ),
        )


class Phase8PostCampaignAnalyzer:
    """Build deterministic campaign economics and a manual-review recommendation."""

    def __init__(
        self,
        database: ProjectDatabase | None = None,
        *,
        campaign: TestnetShadowCampaign | None = None,
        reports: FinalPromotionReportEngine | None = None,
        monitor: Phase7CampaignMonitor | None = None,
        policy: Phase8AnalysisPolicy | None = None,
    ) -> None:
        self.database = database or ProjectDatabase()
        self.database.initialize()
        self.campaign = campaign or TestnetShadowCampaign(self.database)
        self.reports = reports or FinalPromotionReportEngine(self.database)
        self.monitor = monitor or Phase7CampaignMonitor(
            self.database,
            campaign=self.campaign,
            reports=self.reports,
        )
        self.policy = policy or Phase8AnalysisPolicy.from_environment()

    def preview(self, campaign_id: str, *, now_ms: int | None = None) -> dict[str, Any]:
        campaign = self.campaign.get(_identifier(campaign_id, "campaign_id"))
        if campaign is None:
            raise KeyError(campaign_id)
        return self._build(campaign, now_ms=now_ms)

    def analyze(
        self,
        campaign_id: str,
        *,
        actor: str,
        now_ms: int | None = None,
    ) -> dict[str, Any]:
        campaign = self.campaign.get(_identifier(campaign_id, "campaign_id"))
        if campaign is None:
            raise KeyError(campaign_id)
        if str(campaign.get("status") or "") not in _TERMINAL:
            raise ValueError("post-campaign analysis requires a terminal campaign")
        payload = self._build(campaign, now_ms=now_ms)
        clean_actor = _identifier(actor, "actor")
        evidence_hash = str(payload["evidence_sha256"])
        analysis_id = "phase8_" + hashlib.sha256(
            f"{campaign_id}:{evidence_hash}".encode("utf-8")
        ).hexdigest()[:32]
        document = {
            "analysis_id": analysis_id,
            **payload,
            "actor": clean_actor,
        }
        existing = self.database.get_json(_ANALYSIS_NAMESPACE, analysis_id)
        if existing is not None:
            return {**dict(existing["value"]), "version": int(existing["version"])}
        version = self.database.put_json(
            _ANALYSIS_NAMESPACE,
            analysis_id,
            document,
            expected_version=0,
        )
        event_id = self.database.append_event(
            _EVENT_NAMESPACE,
            "post_campaign_analysis",
            analysis_id,
            {
                "campaign_id": campaign_id,
                "recommendation": document["recommendation"]["action"],
                "promotion_recommended": document["recommendation"]["promotion_recommended"],
                "evidence_sha256": evidence_hash,
                "actor": clean_actor,
            },
            created_at_ms=int(document["created_at_ms"]),
        )
        return {**document, "version": version, "event_id": event_id}

    def get(self, analysis_id: str) -> dict[str, Any] | None:
        current = self.database.get_json(
            _ANALYSIS_NAMESPACE,
            _identifier(analysis_id, "analysis_id"),
        )
        if current is None:
            return None
        return {**dict(current["value"]), "version": int(current["version"])}

    def latest_for_campaign(self, campaign_id: str) -> dict[str, Any] | None:
        clean = _identifier(campaign_id, "campaign_id")
        for row in list_json_items(
            self.database,
            _ANALYSIS_NAMESPACE,
            limit=500,
            newest_first=True,
        ):
            value = row.get("value")
            if isinstance(value, Mapping) and str(value.get("campaign_id") or "") == clean:
                return {**dict(value), "version": int(row["version"])}
        return None

    def list(self, *, limit: int = 100) -> list[dict[str, Any]]:
        return [
            {**dict(row["value"]), "version": int(row["version"])}
            for row in list_json_items(
                self.database,
                _ANALYSIS_NAMESPACE,
                limit=min(max(int(limit), 1), 1_000),
                newest_first=True,
            )
            if isinstance(row.get("value"), Mapping)
        ]

    def _build(self, campaign: Mapping[str, Any], *, now_ms: int | None) -> dict[str, Any]:
        timestamp = _timestamp(now_ms)
        campaign_id = str(campaign.get("campaign_id") or "")
        fills = self.monitor.actual_fills(campaign_id)
        metrics = campaign.get("metrics") if isinstance(campaign.get("metrics"), Mapping) else {}
        evidence = campaign.get("last_evidence") if isinstance(campaign.get("last_evidence"), Mapping) else {}
        validation = evidence.get("fill_validation") if isinstance(evidence.get("fill_validation"), Mapping) else {}
        report_id = str(campaign.get("final_report_id") or "")
        report = self.reports.get(report_id) if report_id else None

        total_notional = round(sum(_fill_notional(item) for item in fills), 12)
        total_fees = round(sum(_finite(item.get("actual_fee")) for item in fills), 12)
        fee_bps = round(total_fees / total_notional * 10_000.0, 8) if total_notional > 0 else 0.0
        maker_count = sum(bool(item.get("is_maker")) for item in fills)
        maker_rate = round(maker_count / len(fills) * 100.0, 8) if fills else 0.0
        times = sorted(int(item.get("last_exec_time_ms", 0) or 0) for item in fills if int(item.get("last_exec_time_ms", 0) or 0) > 0)
        duration_seconds = max((times[-1] - times[0]) / 1000.0, 0.0) if len(times) >= 2 else 0.0
        fills_per_minute = round(len(fills) / max(duration_seconds / 60.0, 1.0 / 60.0), 8) if fills else 0.0
        quantities = [_finite(item.get("filled_quantity")) for item in fills]

        drawdown = _execution_cost_drawdown(fills, validation)
        canonical_drawdown = max(
            _finite(metrics.get("portfolio_drawdown_percent")),
            _finite(metrics.get("max_drawdown_percent")),
            _finite(metrics.get("drawdown_percent")),
        )
        observed_drawdown = max(drawdown["percent"], canonical_drawdown)
        drawdown_source = "canonical_portfolio" if canonical_drawdown >= drawdown["percent"] and canonical_drawdown > 0 else "execution_cost"

        matched = int(metrics.get("matched_fill_count", 0) or 0)
        identity_counts = {
            "orphan_execution_count": int(metrics.get("orphan_execution_count", 0) or 0),
            "duplicate_order_count": int(metrics.get("duplicate_order_count", 0) or 0),
            "unresolved_order_count": int(metrics.get("unresolved_order_count", 0) or 0),
            "unmatched_paper_count": int(metrics.get("unmatched_paper_count", 0) or 0),
            "unmatched_testnet_count": int(metrics.get("unmatched_testnet_count", 0) or 0),
        }
        unique_exec_ids = {str(item.get("exec_id") or "") for item in fills if str(item.get("exec_id") or "")}
        p95_slippage = _finite(validation.get("p95_slippage_divergence_bps"))
        p95_latency = _finite(validation.get("p95_latency_divergence_ms"))
        partial_rate = _finite(validation.get("testnet_partial_fill_rate_percent"))
        validation_present = bool(validation)
        completed = str(campaign.get("status") or "") == "completed"
        report_eligible = bool((report or {}).get("eligible_for_manual_decision"))

        gates = {
            "campaign_completed": completed,
            "minimum_20_matched_fills": matched >= 20,
            "minimum_actual_private_fills": len(fills) >= self.policy.minimum_actual_private_fills,
            "unique_private_execution_ids": len(unique_exec_ids) == len(fills) and bool(fills),
            "actual_fees_present": total_fees > 0 and bool(metrics.get("actual_execution_fees")),
            "zero_identity_failures": all(value == 0 for value in identity_counts.values()),
            "final_report_eligible": report_eligible,
            "fill_divergence_present": validation_present,
            "drawdown_within_limit": observed_drawdown <= self.policy.maximum_execution_cost_drawdown_percent,
            "actual_fee_rate_within_limit": fee_bps <= self.policy.maximum_actual_fee_bps,
            "p95_slippage_within_limit": validation_present and p95_slippage <= self.policy.maximum_p95_slippage_bps,
            "p95_latency_within_limit": validation_present and p95_latency <= self.policy.maximum_p95_latency_ms,
            "partial_fill_rate_within_limit": validation_present and partial_rate <= self.policy.maximum_partial_fill_rate_percent,
        }
        failed = sorted(name for name, passed in gates.items() if not passed)
        recommendation = _recommendation(
            status=str(campaign.get("status") or "unknown"),
            failed_gates=failed,
            all_passed=not failed,
        )
        body = {
            "schema_version": 1,
            "campaign_id": campaign_id,
            "experiment_id": str(campaign.get("experiment_id") or ""),
            "final_report_id": report_id,
            "campaign_status": str(campaign.get("status") or "unknown"),
            "created_at_ms": timestamp,
            "policy": asdict(self.policy),
            "execution": {
                "actual_private_fill_count": len(fills),
                "matched_fill_count": matched,
                "unique_exec_id_count": len(unique_exec_ids),
                "executed_notional_usdt": total_notional,
                "actual_fee_total": total_fees,
                "actual_fee_bps": fee_bps,
                "maker_fill_count": maker_count,
                "taker_fill_count": max(len(fills) - maker_count, 0),
                "maker_rate_percent": maker_rate,
                "median_fill_quantity": round(statistics.median(quantities), 12) if quantities else 0.0,
                "duration_seconds": round(duration_seconds, 8),
                "fills_per_minute": fills_per_minute,
            },
            "divergence": {
                "present": validation_present,
                "p95_latency_divergence_ms": p95_latency,
                "p95_slippage_divergence_bps": p95_slippage,
                "p95_fee_delta_bps": _finite(validation.get("p95_fee_delta_bps")),
                "maximum_fill_ratio_delta": _finite(validation.get("maximum_fill_ratio_delta")),
                "partial_fill_rate_percent": partial_rate,
                "promotion_eligible": bool(validation.get("promotion_eligible")),
                "failed_gates": list(validation.get("failed_gates") or []),
            },
            "drawdown": {
                **drawdown,
                "canonical_portfolio_drawdown_percent": round(canonical_drawdown, 8),
                "observed_drawdown_percent": round(observed_drawdown, 8),
                "source": drawdown_source,
                "limit_percent": self.policy.maximum_execution_cost_drawdown_percent,
                "breached": observed_drawdown > self.policy.maximum_execution_cost_drawdown_percent,
            },
            "identity_integrity": identity_counts,
            "gates": gates,
            "failed_gates": failed,
            "recommendation": recommendation,
            "manual_decision_required": True,
            "automatic_promotion": False,
            "runtime_flags_changed": False,
            "mainnet_enabled": False,
        }
        body["evidence_sha256"] = hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
        ).hexdigest()
        return body


def _execution_cost_drawdown(
    fills: list[dict[str, Any]],
    validation: Mapping[str, Any],
) -> dict[str, float]:
    pairs = validation.get("pairs") if isinstance(validation.get("pairs"), list) else []
    slippage_by_link = {
        str(item.get("match_id") or ""): max(_finite(item.get("testnet_slippage_bps")), 0.0)
        for item in pairs
        if isinstance(item, Mapping)
    }
    cumulative_cost = 0.0
    maximum_cost = 0.0
    total_notional = 0.0
    for fill in sorted(fills, key=lambda item: (int(item.get("last_exec_time_ms", 0) or 0), str(item.get("exec_id") or ""))):
        notional = _fill_notional(fill)
        fee = max(_finite(fill.get("actual_fee")), 0.0)
        slippage_bps = slippage_by_link.get(str(fill.get("order_link_id") or ""), 0.0)
        adverse_slippage = notional * slippage_bps / 10_000.0
        cumulative_cost += fee + adverse_slippage
        maximum_cost = max(maximum_cost, cumulative_cost)
        total_notional += notional
    percent = maximum_cost / total_notional * 100.0 if total_notional > 0 else 0.0
    return {
        "execution_cost_drawdown_usdt": round(maximum_cost, 12),
        "execution_cost_drawdown_percent": round(percent, 8),
        "percent": round(percent, 8),
    }


def _recommendation(*, status: str, failed_gates: list[str], all_passed: bool) -> dict[str, Any]:
    if all_passed:
        action = "PROMOTE_TO_EXTENDED_TESTNET"
        reason = "all Phase 8 campaign quality gates passed"
    elif status in {"blocked", "cancelled"} or any(
        token in gate
        for gate in failed_gates
        for token in ("identity", "report", "actual_fees", "unique_private")
    ):
        action = "REJECT_AND_INVESTIGATE"
        reason = "terminal integrity or evidence gate failed"
    elif status == "completed":
        action = "HOLD_AND_TUNE"
        reason = "campaign completed but one or more quality gates require tuning"
    else:
        action = "CONTINUE_BOUNDED_CAMPAIGN"
        reason = "campaign is not terminal"
    return {
        "action": action,
        "reason": reason,
        "promotion_recommended": action == "PROMOTE_TO_EXTENDED_TESTNET",
        "failed_gates": failed_gates,
        "manual_decision_required": True,
    }


def _fill_notional(fill: Mapping[str, Any]) -> float:
    value = _finite(fill.get("executed_value"))
    if value > 0:
        return value
    return max(_finite(fill.get("filled_quantity")) * _finite(fill.get("average_fill_price")), 0.0)


def _finite(value: Any) -> float:
    try:
        parsed = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return parsed if math.isfinite(parsed) else 0.0


def _timestamp(value: int | None) -> int:
    timestamp = int(time.time() * 1000) if value is None else int(value)
    if timestamp <= 0:
        raise ValueError("timestamp must be positive")
    return timestamp


def _identifier(value: Any, name: str) -> str:
    clean = str(value or "").strip()
    if not clean or len(clean) > 200:
        raise ValueError(f"invalid {name}")
    if any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.:-" for character in clean):
        raise ValueError(f"invalid {name}")
    return clean


def _bounded_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    if not math.isfinite(value):
        value = default
    return min(max(value, minimum), maximum)


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return min(max(value, minimum), maximum)


__all__ = ["Phase8AnalysisPolicy", "Phase8PostCampaignAnalyzer"]
