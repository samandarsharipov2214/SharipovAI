"""Phase 9 campaign results, risk metrics and fail-closed scaling preparation."""
from __future__ import annotations

import hashlib
import math
import time
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from storage import ProjectDatabase, list_json_items

_RESULTS_NS = "phase9_campaign_results"
_SCALING_NS = "phase9_scaling_plans"


@dataclass(frozen=True, slots=True)
class ScalingPolicy:
    current_notional_usdt: float = 25.0
    maximum_next_notional_usdt: float = 50.0
    minimum_campaigns: int = 2
    minimum_fills: int = 40
    minimum_profit_factor: float = 1.05
    minimum_win_rate: float = 0.40
    maximum_drawdown_bps: float = 250.0
    maximum_price_divergence_bps: float = 25.0
    maximum_fee_ratio_bps: float = 30.0


class CampaignResultsService:
    def __init__(self, database: ProjectDatabase | None = None, *, policy: ScalingPolicy | None = None) -> None:
        self.database = database or ProjectDatabase()
        self.database.initialize()
        self.policy = policy or ScalingPolicy()

    def build_report(
        self,
        analysis: Mapping[str, Any],
        fills: Sequence[Mapping[str, Any]],
        *,
        generated_at_ms: int | None = None,
    ) -> dict[str, Any]:
        campaign_id = str(analysis.get("campaign_id") or "").strip()
        if not campaign_id:
            raise ValueError("campaign_id is required")
        timestamp = int(time.time() * 1000) if generated_at_ms is None else int(generated_at_ms)
        trades = _closed_trades(fills)
        equity = 0.0
        peak = 0.0
        max_drawdown = 0.0
        gross_profit = 0.0
        gross_loss = 0.0
        wins = 0
        for trade in trades:
            equity += trade["net_pnl_usdt"]
            peak = max(peak, equity)
            max_drawdown = max(max_drawdown, peak - equity)
            if trade["net_pnl_usdt"] > 0:
                wins += 1
                gross_profit += trade["net_pnl_usdt"]
            elif trade["net_pnl_usdt"] < 0:
                gross_loss += abs(trade["net_pnl_usdt"])
        closed_notional = sum(trade["exit_notional_usdt"] for trade in trades)
        max_drawdown_bps = max_drawdown / closed_notional * 10_000.0 if closed_notional else 0.0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else (math.inf if gross_profit > 0 else 0.0)
        win_rate = wins / len(trades) if trades else 0.0
        pnl = analysis.get("pnl") if isinstance(analysis.get("pnl"), Mapping) else {}
        divergence = analysis.get("divergence") if isinstance(analysis.get("divergence"), Mapping) else {}
        report = {
            "schema_version": 1,
            "report_id": "p9r_" + hashlib.sha256(f"{campaign_id}:{timestamp}".encode()).hexdigest()[:32],
            "campaign_id": campaign_id,
            "analysis_id": str(analysis.get("analysis_id") or ""),
            "generated_at_ms": timestamp,
            "fill_count": int(analysis.get("fill_count") or len(fills)),
            "matched_fill_count": int(analysis.get("matched_fill_count") or 0),
            "pnl": dict(pnl),
            "divergence": dict(divergence),
            "risk_metrics": {
                "closed_trade_count": len(trades),
                "winning_trade_count": wins,
                "losing_trade_count": len(trades) - wins,
                "win_rate": round(win_rate, 8),
                "gross_profit_usdt": round(gross_profit, 12),
                "gross_loss_usdt": round(gross_loss, 12),
                "profit_factor": "infinity" if math.isinf(profit_factor) else round(profit_factor, 8),
                "maximum_drawdown_usdt": round(max_drawdown, 12),
                "maximum_drawdown_bps": round(max_drawdown_bps, 6),
                "closed_notional_usdt": round(closed_notional, 12),
            },
            "trades": trades[-500:],
            "source_failed_gates": list(analysis.get("failed_gates") or []),
            "runtime_flags_changed": False,
            "mainnet_enabled": False,
        }
        current = self.database.get_json(_RESULTS_NS, campaign_id)
        self.database.put_json(_RESULTS_NS, campaign_id, report, expected_version=int(current["version"]) if current else 0)
        self.database.append_event(_RESULTS_NS, "campaign_results_report", campaign_id, report, created_at_ms=timestamp)
        return report

    def prepare_scaling(self, reports: Sequence[Mapping[str, Any]], *, actor: str, reason: str) -> dict[str, Any]:
        actor = actor.strip()
        reason = reason.strip()
        if not actor or not reason:
            raise ValueError("actor and reason are required")
        clean = [dict(item) for item in reports if item.get("campaign_id")]
        fill_count = sum(int(item.get("matched_fill_count") or 0) for item in clean)
        metrics = [item.get("risk_metrics") for item in clean if isinstance(item.get("risk_metrics"), Mapping)]
        worst_drawdown = max((float(item.get("maximum_drawdown_bps") or 0.0) for item in metrics), default=0.0)
        finite_pf = [float(item.get("profit_factor") or 0.0) for item in metrics if item.get("profit_factor") != "infinity"]
        minimum_pf = min(finite_pf, default=999.0 if metrics else 0.0)
        minimum_win_rate = min((float(item.get("win_rate") or 0.0) for item in metrics), default=0.0)
        maximum_divergence = max((abs(float((item.get("divergence") or {}).get("price_divergence_bps") or 0.0)) for item in clean), default=0.0)
        maximum_fee_ratio = max((float(item.get("fee_ratio_bps") or 0.0) for item in clean), default=0.0)
        gates = {
            "minimum_successful_campaigns": len(clean) >= self.policy.minimum_campaigns,
            "minimum_total_matched_fills": fill_count >= self.policy.minimum_fills,
            "all_source_gates_clean": all(not item.get("source_failed_gates") for item in clean),
            "profit_factor": minimum_pf >= self.policy.minimum_profit_factor,
            "win_rate": minimum_win_rate >= self.policy.minimum_win_rate,
            "drawdown": worst_drawdown <= self.policy.maximum_drawdown_bps,
            "price_divergence": maximum_divergence <= self.policy.maximum_price_divergence_bps,
            "fee_ratio": maximum_fee_ratio <= self.policy.maximum_fee_ratio_bps,
        }
        failed = sorted(name for name, passed in gates.items() if not passed)
        next_notional = min(self.policy.current_notional_usdt * 1.5, self.policy.maximum_next_notional_usdt)
        timestamp = int(time.time() * 1000)
        plan_id = "p9s_" + hashlib.sha256(f"{timestamp}:{actor}:{','.join(sorted(str(r['campaign_id']) for r in clean))}".encode()).hexdigest()[:32]
        plan = {
            "schema_version": 1,
            "plan_id": plan_id,
            "created_at_ms": timestamp,
            "actor": actor,
            "reason": reason,
            "campaign_ids": [str(item["campaign_id"]) for item in clean],
            "evidence": {"campaign_count": len(clean), "matched_fill_count": fill_count, "minimum_profit_factor": minimum_pf, "minimum_win_rate": minimum_win_rate, "maximum_drawdown_bps": worst_drawdown, "maximum_price_divergence_bps": maximum_divergence, "maximum_fee_ratio_bps": maximum_fee_ratio},
            "gates": gates,
            "failed_gates": failed,
            "status": "eligible_for_manual_scaling_review" if not failed else "blocked",
            "current_notional_usdt": self.policy.current_notional_usdt,
            "proposed_next_notional_usdt": next_notional if not failed else self.policy.current_notional_usdt,
            "manual_approval_required": True,
            "automatic_scaling": False,
            "runtime_flags_changed": False,
            "mainnet_enabled": False,
        }
        self.database.put_json(_SCALING_NS, plan_id, plan, expected_version=0)
        self.database.append_event(_SCALING_NS, "scaling_plan_created", plan_id, plan, created_at_ms=timestamp)
        return plan

    def get_report(self, campaign_id: str) -> dict[str, Any] | None:
        row = self.database.get_json(_RESULTS_NS, campaign_id)
        return dict(row["value"]) if row else None

    def list_reports(self, limit: int = 100) -> list[dict[str, Any]]:
        return [dict(row["value"]) for row in list_json_items(self.database, _RESULTS_NS, limit=limit, newest_first=True)]

    def list_scaling_plans(self, limit: int = 100) -> list[dict[str, Any]]:
        return [dict(row["value"]) for row in list_json_items(self.database, _SCALING_NS, limit=limit, newest_first=True)]


def _closed_trades(fills: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    inventory: dict[str, list[list[float]]] = {}
    trades: list[dict[str, Any]] = []
    rows = sorted(fills, key=lambda row: int(row.get("last_exec_time_ms", row.get("exec_time_ms", 0)) or 0))
    for item in rows:
        symbol = str(item.get("symbol") or "UNKNOWN")
        side = str(item.get("side") or "").lower()
        qty = _finite(item.get("filled_quantity", item.get("exec_quantity")))
        price = _finite(item.get("average_fill_price", item.get("exec_price")))
        fee = _finite(item.get("actual_fee", item.get("exec_fee")))
        if qty <= 0 or price <= 0:
            continue
        inventory.setdefault(symbol, [])
        if side == "buy":
            inventory[symbol].append([qty, price, fee])
            continue
        if side != "sell":
            continue
        remaining = qty
        while remaining > 1e-15 and inventory[symbol]:
            lot = inventory[symbol][0]
            matched = min(remaining, lot[0])
            allocated_entry_fee = lot[2] * matched / lot[0] if lot[0] else 0.0
            allocated_exit_fee = fee * matched / qty if qty else 0.0
            gross = matched * (price - lot[1])
            trades.append({"symbol": symbol, "quantity": round(matched, 12), "entry_price": round(lot[1], 12), "exit_price": round(price, 12), "gross_pnl_usdt": round(gross, 12), "fees_usdt": round(allocated_entry_fee + allocated_exit_fee, 12), "net_pnl_usdt": round(gross - allocated_entry_fee - allocated_exit_fee, 12), "exit_notional_usdt": round(matched * price, 12)})
            lot[0] -= matched
            lot[2] -= allocated_entry_fee
            remaining -= matched
            if lot[0] <= 1e-15:
                inventory[symbol].pop(0)
    return trades


def _finite(value: Any) -> float:
    try:
        parsed = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return parsed if math.isfinite(parsed) else 0.0


__all__ = ["CampaignResultsService", "ScalingPolicy"]
