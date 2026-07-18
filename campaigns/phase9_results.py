"""Phase 9 campaign results, risk metrics and fail-closed scaling preparation."""
from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from storage import ProjectDatabase, VersionConflict, list_json_items

_RESULTS_NS = "phase9_campaign_results"
_REPORT_INDEX_NS = "phase9_campaign_report_index"
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

    def __post_init__(self) -> None:
        numeric = {
            "current_notional_usdt": self.current_notional_usdt,
            "maximum_next_notional_usdt": self.maximum_next_notional_usdt,
            "minimum_profit_factor": self.minimum_profit_factor,
            "minimum_win_rate": self.minimum_win_rate,
            "maximum_drawdown_bps": self.maximum_drawdown_bps,
            "maximum_price_divergence_bps": self.maximum_price_divergence_bps,
            "maximum_fee_ratio_bps": self.maximum_fee_ratio_bps,
        }
        parsed = {name: _required_finite(value, name) for name, value in numeric.items()}
        if not 0 < parsed["current_notional_usdt"] <= 50:
            raise ValueError("current_notional_usdt must be within (0, 50]")
        if not parsed["current_notional_usdt"] <= parsed["maximum_next_notional_usdt"] <= 50:
            raise ValueError("maximum_next_notional_usdt must be within current notional and 50")
        if int(self.minimum_campaigns) < 1 or int(self.minimum_fills) < 1:
            raise ValueError("minimum campaign and fill counts must be positive")
        if parsed["minimum_profit_factor"] < 0:
            raise ValueError("minimum_profit_factor must be non-negative")
        if not 0 <= parsed["minimum_win_rate"] <= 1:
            raise ValueError("minimum_win_rate must be within [0, 1]")
        if any(parsed[name] < 0 for name in (
            "maximum_drawdown_bps",
            "maximum_price_divergence_bps",
            "maximum_fee_ratio_bps",
        )):
            raise ValueError("maximum risk metrics must be non-negative")


class CampaignResultsService:
    def __init__(
        self,
        database: ProjectDatabase | None = None,
        *,
        policy: ScalingPolicy | None = None,
    ) -> None:
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
        if not isinstance(analysis, Mapping):
            raise ValueError("analysis must be a mapping")
        if not isinstance(fills, Sequence) or isinstance(fills, (str, bytes)):
            raise ValueError("fills must be a sequence")
        campaign_id = _required_text(analysis.get("campaign_id"), "campaign_id", 128)
        analysis_id = _required_text(analysis.get("analysis_id"), "analysis_id", 128)
        timestamp = _timestamp(generated_at_ms)
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
        profit_factor: float | str
        if gross_loss > 0:
            profit_factor = round(gross_profit / gross_loss, 8)
        else:
            profit_factor = "infinity" if gross_profit > 0 else 0.0
        win_rate = wins / len(trades) if trades else 0.0
        pnl = _finite_mapping(
            analysis.get("pnl"),
            allowed=(
                "gross_realized_pnl_usdt",
                "net_realized_pnl_usdt",
                "fees_usdt",
                "turnover_usdt",
                "open_inventory_quantity",
                "open_inventory_cost_usdt",
            ),
            name="pnl",
        )
        divergence = _finite_mapping(
            analysis.get("divergence"),
            allowed=(
                "paper_average_price",
                "testnet_average_price",
                "price_divergence_bps",
                "paper_fee_usdt",
                "testnet_fee_usdt",
                "fee_divergence_usdt",
            ),
            name="divergence",
        )
        material = {
            "schema_version": 2,
            "campaign_id": campaign_id,
            "analysis_id": analysis_id,
            "source_analysis_generated_at_ms": _optional_non_negative_int(
                analysis.get("generated_at_ms")
            ),
            "fill_count": _non_negative_int(
                analysis.get("fill_count", len(fills)), "fill_count"
            ),
            "matched_fill_count": _non_negative_int(
                analysis.get("matched_fill_count", 0), "matched_fill_count"
            ),
            "pnl": pnl,
            "divergence": divergence,
            "fee_ratio_bps": _required_finite(
                analysis.get("fee_ratio_bps", 0.0), "fee_ratio_bps"
            ),
            "risk_metrics": {
                "closed_trade_count": len(trades),
                "winning_trade_count": wins,
                "losing_trade_count": len(trades) - wins,
                "win_rate": round(win_rate, 8),
                "gross_profit_usdt": round(gross_profit, 12),
                "gross_loss_usdt": round(gross_loss, 12),
                "profit_factor": profit_factor,
                "maximum_drawdown_usdt": round(max_drawdown, 12),
                "maximum_drawdown_bps": round(max_drawdown_bps, 6),
                "closed_notional_usdt": round(closed_notional, 12),
            },
            "trades": trades[-500:],
            "source_failed_gates": sorted(
                str(item) for item in (analysis.get("failed_gates") or [])
            ),
            "runtime_flags_changed": False,
            "mainnet_enabled": False,
        }
        if material["fee_ratio_bps"] < 0:
            raise ValueError("fee_ratio_bps must be non-negative")
        evidence_hash = hashlib.sha256(_canonical_json(material)).hexdigest()
        report_id = "p9r_" + evidence_hash[:32]
        report = {
            **material,
            "report_id": report_id,
            "generated_at_ms": timestamp,
            "evidence_sha256": evidence_hash,
        }
        existing = self.database.get_json(_RESULTS_NS, report_id)
        if existing:
            if not _same_report(existing["value"], report):
                raise VersionConflict("Phase 9 report identity collision")
            report = dict(existing["value"])
        else:
            self.database.put_json(_RESULTS_NS, report_id, report, expected_version=0)
            self.database.append_event(
                _RESULTS_NS,
                "campaign_results_report",
                report_id,
                report,
                created_at_ms=timestamp,
            )
        self._update_latest_index(report)
        return report

    def prepare_scaling(
        self,
        reports: Sequence[Mapping[str, Any]],
        *,
        actor: str,
        reason: str,
    ) -> dict[str, Any]:
        actor = _required_text(actor, "actor", 128)
        reason = _required_text(reason, "reason", 1000)
        if not isinstance(reports, Sequence) or isinstance(reports, (str, bytes)):
            raise ValueError("reports must be a sequence")
        by_campaign: dict[str, dict[str, Any]] = {}
        invalid_report_ids: list[str] = []
        for raw in reports:
            if not isinstance(raw, Mapping):
                invalid_report_ids.append("non_mapping")
                continue
            item = dict(raw)
            campaign_id = str(item.get("campaign_id") or "").strip()
            if not campaign_id or not _report_integrity_valid(item):
                invalid_report_ids.append(str(item.get("report_id") or campaign_id or "unknown"))
                continue
            previous = by_campaign.get(campaign_id)
            if previous is None or int(item.get("generated_at_ms") or 0) > int(
                previous.get("generated_at_ms") or 0
            ):
                by_campaign[campaign_id] = item
        clean = [by_campaign[key] for key in sorted(by_campaign)]
        fill_count = sum(
            _non_negative_int(item.get("matched_fill_count", 0), "matched_fill_count")
            for item in clean
        )
        metrics = [
            item.get("risk_metrics")
            for item in clean
            if isinstance(item.get("risk_metrics"), Mapping)
        ]
        worst_drawdown = max(
            (
                _required_finite(item.get("maximum_drawdown_bps", 0.0), "maximum_drawdown_bps")
                for item in metrics
            ),
            default=0.0,
        )
        finite_pf = [
            _required_finite(item.get("profit_factor", 0.0), "profit_factor")
            for item in metrics
            if item.get("profit_factor") != "infinity"
        ]
        minimum_pf = min(finite_pf, default=999.0 if metrics else 0.0)
        minimum_win_rate = min(
            (
                _required_finite(item.get("win_rate", 0.0), "win_rate")
                for item in metrics
            ),
            default=0.0,
        )
        maximum_divergence = max(
            (
                abs(
                    _required_finite(
                        (item.get("divergence") or {}).get("price_divergence_bps", 0.0),
                        "price_divergence_bps",
                    )
                )
                for item in clean
            ),
            default=0.0,
        )
        maximum_fee_ratio = max(
            (
                _required_finite(item.get("fee_ratio_bps", 0.0), "fee_ratio_bps")
                for item in clean
            ),
            default=0.0,
        )
        gates = {
            "all_report_evidence_valid": not invalid_report_ids,
            "minimum_successful_campaigns": len(clean) >= self.policy.minimum_campaigns,
            "minimum_total_matched_fills": fill_count >= self.policy.minimum_fills,
            "all_source_gates_clean": all(
                not item.get("source_failed_gates") for item in clean
            ),
            "profit_factor": minimum_pf >= self.policy.minimum_profit_factor,
            "win_rate": minimum_win_rate >= self.policy.minimum_win_rate,
            "drawdown": worst_drawdown <= self.policy.maximum_drawdown_bps,
            "price_divergence": maximum_divergence
            <= self.policy.maximum_price_divergence_bps,
            "fee_ratio": maximum_fee_ratio <= self.policy.maximum_fee_ratio_bps,
        }
        failed = sorted(name for name, passed in gates.items() if not passed)
        next_notional = min(
            self.policy.current_notional_usdt * 1.5,
            self.policy.maximum_next_notional_usdt,
        )
        timestamp = int(time.time() * 1000)
        plan_material = {
            "actor": actor,
            "reason": reason,
            "campaign_ids": [str(item["campaign_id"]) for item in clean],
            "report_ids": [str(item["report_id"]) for item in clean],
            "invalid_report_ids": sorted(invalid_report_ids),
            "evidence": {
                "campaign_count": len(clean),
                "matched_fill_count": fill_count,
                "minimum_profit_factor": minimum_pf,
                "minimum_win_rate": minimum_win_rate,
                "maximum_drawdown_bps": worst_drawdown,
                "maximum_price_divergence_bps": maximum_divergence,
                "maximum_fee_ratio_bps": maximum_fee_ratio,
            },
            "gates": gates,
            "failed_gates": failed,
            "status": "eligible_for_manual_scaling_review" if not failed else "blocked",
            "current_notional_usdt": self.policy.current_notional_usdt,
            "proposed_next_notional_usdt": (
                next_notional if not failed else self.policy.current_notional_usdt
            ),
            "manual_approval_required": True,
            "automatic_scaling": False,
            "runtime_flags_changed": False,
            "mainnet_enabled": False,
        }
        evidence_hash = hashlib.sha256(_canonical_json(plan_material)).hexdigest()
        plan_id = "p9s_" + evidence_hash[:32]
        plan = {
            "schema_version": 2,
            "plan_id": plan_id,
            "created_at_ms": timestamp,
            **plan_material,
            "evidence_sha256": evidence_hash,
        }
        existing = self.database.get_json(_SCALING_NS, plan_id)
        if existing:
            comparable = dict(existing["value"])
            comparable.pop("created_at_ms", None)
            expected = dict(plan)
            expected.pop("created_at_ms", None)
            if comparable != expected:
                raise VersionConflict("scaling plan identity collision")
            return dict(existing["value"])
        self.database.put_json(_SCALING_NS, plan_id, plan, expected_version=0)
        self.database.append_event(
            _SCALING_NS,
            "scaling_plan_created",
            plan_id,
            plan,
            created_at_ms=timestamp,
        )
        return plan

    def get_report(self, campaign_id: str) -> dict[str, Any] | None:
        campaign_id = _required_text(campaign_id, "campaign_id", 128)
        index = self.database.get_json(_REPORT_INDEX_NS, campaign_id)
        if index:
            report_id = str(index["value"].get("report_id") or "")
            if report_id:
                row = self.database.get_json(_RESULTS_NS, report_id)
                if row:
                    return dict(row["value"])
        legacy = self.database.get_json(_RESULTS_NS, campaign_id)
        return dict(legacy["value"]) if legacy else None

    def list_reports(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = list_json_items(
            self.database,
            _RESULTS_NS,
            limit=min(max(int(limit) * 3, 1), 1000),
            newest_first=True,
        )
        reports: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows:
            value = dict(row["value"])
            report_id = str(value.get("report_id") or "")
            if not report_id:
                report_id = f"legacy:{value.get('campaign_id', '')}"
            if report_id in seen or not value.get("campaign_id"):
                continue
            seen.add(report_id)
            reports.append(value)
            if len(reports) >= limit:
                break
        return reports

    def list_scaling_plans(self, limit: int = 100) -> list[dict[str, Any]]:
        return [
            dict(row["value"])
            for row in list_json_items(
                self.database,
                _SCALING_NS,
                limit=limit,
                newest_first=True,
            )
        ]

    def _update_latest_index(self, report: Mapping[str, Any]) -> None:
        campaign_id = str(report["campaign_id"])
        row = self.database.get_json(_REPORT_INDEX_NS, campaign_id)
        current = dict(row["value"]) if row else {}
        current_generated = int(current.get("generated_at_ms") or -1)
        report_generated = int(report.get("generated_at_ms") or 0)
        if current and current_generated > report_generated:
            return
        index = {
            "schema_version": 1,
            "campaign_id": campaign_id,
            "report_id": str(report["report_id"]),
            "analysis_id": str(report.get("analysis_id") or ""),
            "generated_at_ms": report_generated,
            "evidence_sha256": str(report.get("evidence_sha256") or ""),
        }
        if current == index:
            return
        self.database.put_json(
            _REPORT_INDEX_NS,
            campaign_id,
            index,
            expected_version=int(row["version"]) if row else 0,
        )
        self.database.append_event(
            _REPORT_INDEX_NS,
            "latest_campaign_report_index",
            campaign_id,
            index,
            created_at_ms=report_generated,
        )


def _closed_trades(fills: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    inventory: dict[str, list[list[float]]] = {}
    trades: list[dict[str, Any]] = []
    rows = sorted(
        fills,
        key=lambda row: _non_negative_int(
            row.get("last_exec_time_ms", row.get("exec_time_ms", 0)),
            "exec_time_ms",
        ),
    )
    for item in rows:
        if not isinstance(item, Mapping):
            raise ValueError("fill must be a mapping")
        symbol = _required_text(item.get("symbol"), "fill symbol", 32).upper()
        side = str(item.get("side") or "").strip().lower()
        qty = _required_finite(
            item.get("filled_quantity", item.get("exec_quantity")),
            "filled_quantity",
        )
        price = _required_finite(
            item.get("average_fill_price", item.get("exec_price")),
            "average_fill_price",
        )
        fee = _required_finite(
            item.get("actual_fee", item.get("exec_fee", 0.0)),
            "actual_fee",
        )
        if qty <= 0 or price <= 0 or fee < 0:
            raise ValueError("fill quantity and price must be positive and fee non-negative")
        if side not in {"buy", "sell"}:
            raise ValueError("fill side must be buy or sell")
        inventory.setdefault(symbol, [])
        if side == "buy":
            inventory[symbol].append([qty, price, fee])
            continue
        remaining = qty
        while remaining > 1e-15 and inventory[symbol]:
            lot = inventory[symbol][0]
            matched = min(remaining, lot[0])
            allocated_entry_fee = lot[2] * matched / lot[0] if lot[0] else 0.0
            allocated_exit_fee = fee * matched / qty if qty else 0.0
            gross = matched * (price - lot[1])
            trades.append(
                {
                    "symbol": symbol,
                    "quantity": round(matched, 12),
                    "entry_price": round(lot[1], 12),
                    "exit_price": round(price, 12),
                    "gross_pnl_usdt": round(gross, 12),
                    "fees_usdt": round(
                        allocated_entry_fee + allocated_exit_fee, 12
                    ),
                    "net_pnl_usdt": round(
                        gross - allocated_entry_fee - allocated_exit_fee, 12
                    ),
                    "exit_notional_usdt": round(matched * price, 12),
                }
            )
            lot[0] -= matched
            lot[2] -= allocated_entry_fee
            remaining -= matched
            if lot[0] <= 1e-15:
                inventory[symbol].pop(0)
    return trades


def _report_material(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: report.get(key)
        for key in (
            "schema_version",
            "campaign_id",
            "analysis_id",
            "source_analysis_generated_at_ms",
            "fill_count",
            "matched_fill_count",
            "pnl",
            "divergence",
            "fee_ratio_bps",
            "risk_metrics",
            "trades",
            "source_failed_gates",
            "runtime_flags_changed",
            "mainnet_enabled",
        )
    }


def _report_integrity_valid(report: Mapping[str, Any]) -> bool:
    supplied = str(report.get("evidence_sha256") or "")
    if len(supplied) != 64 or not str(report.get("report_id") or "").startswith("p9r_"):
        return False
    try:
        expected = hashlib.sha256(_canonical_json(_report_material(report))).hexdigest()
    except (TypeError, ValueError):
        return False
    return supplied == expected and str(report.get("report_id")) == "p9r_" + expected[:32]


def _same_report(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    left_value = dict(left)
    right_value = dict(right)
    left_value.pop("generated_at_ms", None)
    right_value.pop("generated_at_ms", None)
    return left_value == right_value


def _finite_mapping(
    value: Any,
    *,
    allowed: Sequence[str],
    name: str,
) -> dict[str, float]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a mapping")
    unknown = sorted(set(value) - set(allowed))
    if unknown:
        raise ValueError(f"{name} contains unknown fields: {unknown}")
    return {
        key: _required_finite(raw, f"{name}.{key}")
        for key, raw in sorted(value.items())
    }


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _required_text(value: Any, name: str, maximum_length: int) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} is required")
    if len(text) > maximum_length:
        raise ValueError(f"{name} is too long")
    return text


def _required_finite(value: Any, name: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be finite") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{name} must be finite")
    return parsed


def _non_negative_int(value: Any, name: str) -> int:
    parsed = _required_finite(value, name)
    if parsed < 0 or not parsed.is_integer():
        raise ValueError(f"{name} must be a non-negative integer")
    return int(parsed)


def _optional_non_negative_int(value: Any) -> int | None:
    if value is None:
        return None
    return _non_negative_int(value, "generated_at_ms")


def _timestamp(value: int | None) -> int:
    timestamp = int(time.time() * 1000) if value is None else _non_negative_int(
        value, "generated_at_ms"
    )
    return timestamp


__all__ = ["CampaignResultsService", "ScalingPolicy"]
