"""Phase 8 post-campaign analytics over canonical private execution evidence."""
from __future__ import annotations

import hashlib
import json
import math
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any, Mapping

from storage import ProjectDatabase, list_json_items

_NAMESPACE = "phase8_post_campaign_analysis"


@dataclass(frozen=True, slots=True)
class AnalysisPolicy:
    minimum_matched_fills: int = 20
    maximum_abs_price_divergence_bps: float = 60.0
    maximum_fee_ratio_bps: float = 30.0
    minimum_net_pnl_usdt: float = -2.0


class PostCampaignAnalysisService:
    def __init__(self, database: ProjectDatabase | None = None, *, policy: AnalysisPolicy | None = None) -> None:
        self.database = database or ProjectDatabase()
        self.database.initialize()
        self.policy = policy or AnalysisPolicy()

    def analyze(
        self,
        campaign: Mapping[str, Any],
        fills: list[Mapping[str, Any]],
        *,
        generated_at_ms: int | None = None,
    ) -> dict[str, Any]:
        campaign_id = str(campaign.get("campaign_id") or "").strip()
        if not campaign_id:
            raise ValueError("campaign_id is required")
        timestamp = int(time.time() * 1000) if generated_at_ms is None else int(generated_at_ms)
        normalized = [_normalize_fill(item) for item in fills]
        normalized = [item for item in normalized if item["quantity"] > 0 and item["price"] > 0]
        pnl = _realized_pnl(normalized)
        metrics = campaign.get("metrics") if isinstance(campaign.get("metrics"), Mapping) else {}
        matched = int(metrics.get("matched_fill_count") or len(normalized))
        divergence = _divergence(metrics, normalized)
        total_value = sum(item["value"] for item in normalized)
        fees = sum(item["fee"] for item in normalized)
        fee_ratio_bps = fees / total_value * 10_000.0 if total_value > 0 else 0.0
        gates = {
            "campaign_completed": str(campaign.get("status") or "") == "completed",
            "minimum_matched_fills": matched >= self.policy.minimum_matched_fills,
            "actual_private_fills_present": bool(normalized),
            "actual_fees_present": fees > 0,
            "identity_integrity": all(int(metrics.get(name) or 0) == 0 for name in (
                "unmatched_paper_count", "unmatched_testnet_count", "orphan_execution_count",
                "duplicate_order_count", "unresolved_order_count",
            )),
            "price_divergence_within_policy": abs(divergence["price_divergence_bps"]) <= self.policy.maximum_abs_price_divergence_bps,
            "fee_ratio_within_policy": fee_ratio_bps <= self.policy.maximum_fee_ratio_bps,
            "net_pnl_within_policy": pnl["net_realized_pnl_usdt"] >= self.policy.minimum_net_pnl_usdt,
        }
        failed = sorted(name for name, passed in gates.items() if not passed)
        recommendation = _recommendation(gates, pnl, divergence)
        payload = {
            "schema_version": 1,
            "analysis_id": "pca_" + hashlib.sha256(f"{campaign_id}:{timestamp}".encode()).hexdigest()[:32],
            "campaign_id": campaign_id,
            "experiment_id": str(campaign.get("experiment_id") or ""),
            "scope": str(campaign.get("scope") or ""),
            "generated_at_ms": timestamp,
            "fill_count": len(normalized),
            "matched_fill_count": matched,
            "turnover_usdt": round(total_value, 12),
            "fees_usdt": round(fees, 12),
            "fee_ratio_bps": round(fee_ratio_bps, 6),
            "pnl": pnl,
            "divergence": divergence,
            "gates": gates,
            "failed_gates": failed,
            "recommendation": recommendation,
            "manual_decision_required": True,
            "runtime_flags_changed": False,
            "mainnet_enabled": False,
        }
        existing = self.database.get_json(_NAMESPACE, campaign_id)
        self.database.put_json(_NAMESPACE, campaign_id, payload, expected_version=int(existing["version"]) if existing else 0)
        self.database.append_event(_NAMESPACE, "post_campaign_analysis", campaign_id, payload, created_at_ms=timestamp)
        return payload

    def get(self, campaign_id: str) -> dict[str, Any] | None:
        row = self.database.get_json(_NAMESPACE, str(campaign_id))
        return dict(row["value"]) if row else None

    def list(self, *, limit: int = 100) -> list[dict[str, Any]]:
        return [dict(row["value"]) for row in list_json_items(self.database, _NAMESPACE, limit=limit, newest_first=True)]


def _normalize_fill(item: Mapping[str, Any]) -> dict[str, Any]:
    quantity = _finite(item.get("filled_quantity", item.get("exec_quantity")))
    price = _finite(item.get("average_fill_price", item.get("exec_price")))
    value = _finite(item.get("executed_value", item.get("exec_value"))) or quantity * price
    return {
        "symbol": str(item.get("symbol") or "UNKNOWN"),
        "side": str(item.get("side") or "").lower(),
        "quantity": quantity,
        "price": price,
        "value": value,
        "fee": _finite(item.get("actual_fee", item.get("exec_fee"))),
        "time_ms": int(item.get("last_exec_time_ms", item.get("exec_time_ms", 0)) or 0),
    }


def _realized_pnl(fills: list[dict[str, Any]]) -> dict[str, Any]:
    lots: dict[str, deque[list[float]]] = defaultdict(deque)
    gross = 0.0
    closed = 0.0
    for fill in sorted(fills, key=lambda row: (row["time_ms"], row["symbol"])):
        qty = fill["quantity"]
        if fill["side"] == "buy":
            lots[fill["symbol"]].append([qty, fill["price"]])
            continue
        if fill["side"] != "sell":
            continue
        remaining = qty
        while remaining > 1e-15 and lots[fill["symbol"]]:
            lot = lots[fill["symbol"]][0]
            matched = min(remaining, lot[0])
            gross += matched * (fill["price"] - lot[1])
            closed += matched * fill["price"]
            lot[0] -= matched
            remaining -= matched
            if lot[0] <= 1e-15:
                lots[fill["symbol"]].popleft()
    fees = sum(item["fee"] for item in fills)
    return {
        "gross_realized_pnl_usdt": round(gross, 12),
        "fees_usdt": round(fees, 12),
        "net_realized_pnl_usdt": round(gross - fees, 12),
        "closed_notional_usdt": round(closed, 12),
        "return_on_closed_notional_bps": round((gross - fees) / closed * 10_000.0, 6) if closed else 0.0,
        "open_inventory": {symbol: round(sum(qty for qty, _ in queue), 12) for symbol, queue in lots.items() if queue},
    }


def _divergence(metrics: Mapping[str, Any], fills: list[dict[str, Any]]) -> dict[str, Any]:
    weighted_price = sum(row["price"] * row["quantity"] for row in fills)
    quantity = sum(row["quantity"] for row in fills)
    actual_price = weighted_price / quantity if quantity else 0.0
    paper_price = _finite(metrics.get("paper_average_fill_price", metrics.get("paper_avg_price")))
    price_bps = (actual_price - paper_price) / paper_price * 10_000.0 if paper_price > 0 else 0.0
    expected_fees = _finite(metrics.get("paper_fee_total", metrics.get("expected_fee_total")))
    actual_fees = sum(row["fee"] for row in fills)
    return {
        "actual_average_fill_price": round(actual_price, 12),
        "paper_average_fill_price": round(paper_price, 12),
        "price_divergence_bps": round(price_bps, 6),
        "actual_fee_total": round(actual_fees, 12),
        "expected_fee_total": round(expected_fees, 12),
        "fee_divergence_usdt": round(actual_fees - expected_fees, 12),
    }


def _recommendation(gates: Mapping[str, bool], pnl: Mapping[str, Any], divergence: Mapping[str, Any]) -> dict[str, Any]:
    failed = [name for name, passed in gates.items() if not passed]
    if failed:
        action = "reject_or_rerun"
        reason = "One or more hard post-campaign gates failed."
    elif float(pnl.get("net_realized_pnl_usdt") or 0.0) > 0 and abs(float(divergence.get("price_divergence_bps") or 0.0)) <= 60:
        action = "eligible_for_manual_promotion_review"
        reason = "Clean evidence, positive net realized PnL and bounded execution divergence."
    else:
        action = "hold_for_more_testnet_evidence"
        reason = "Hard gates pass, but evidence is not strong enough for promotion recommendation."
    return {"action": action, "reason": reason, "failed_gates": failed, "automatic_promotion": False}


def _finite(value: Any) -> float:
    try:
        parsed = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return parsed if math.isfinite(parsed) else 0.0


__all__ = ["AnalysisPolicy", "PostCampaignAnalysisService"]
