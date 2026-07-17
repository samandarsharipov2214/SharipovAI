"""Phase 7 read-only monitor for bounded Testnet campaigns.

The monitor never changes credentials, execution flags, the kill switch or
Mainnet availability. It projects canonical campaign state and authenticated
private execution evidence into one persistent operational snapshot.
"""
from __future__ import annotations

import json
import math
import os
import threading
import time
from pathlib import Path
from typing import Any, Mapping

from storage import ProjectDatabase

from .core import FinalPromotionReportEngine, TestnetShadowCampaign
from .operations import CampaignOperationsService

_STATE_NAMESPACE = "phase7_campaign_monitor"
_TERMINAL = {"completed", "blocked", "cancelled"}
_TRUE = {"1", "true", "yes", "on"}


class Phase7CampaignMonitor:
    def __init__(
        self,
        database: ProjectDatabase | None = None,
        *,
        operations: CampaignOperationsService | None = None,
        campaign: TestnetShadowCampaign | None = None,
        reports: FinalPromotionReportEngine | None = None,
        report_directory: str | Path | None = None,
    ) -> None:
        self.database = database or ProjectDatabase()
        self.database.initialize()
        self.campaign = campaign or TestnetShadowCampaign(self.database)
        self.reports = reports or FinalPromotionReportEngine(self.database)
        self.operations = operations or CampaignOperationsService(
            self.database,
            campaign=self.campaign,
            reports=self.reports,
        )
        self.interval = _bounded_float("PHASE7_MONITOR_INTERVAL_SECONDS", 3.0, 1.0, 60.0)
        self.stale_after = _bounded_float("PHASE7_MONITOR_STALE_SECONDS", 20.0, 5.0, 300.0)
        self.report_directory = Path(
            report_directory
            or os.getenv("PHASE7_CAMPAIGN_REPORT_DIR", "/var/lib/sharipovai/campaign_reports")
        )
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._state = self._load()

    def enabled(self) -> bool:
        return os.getenv("PHASE7_CAMPAIGN_MONITOR_ENABLED", "0").strip().lower() in _TRUE

    def start(self) -> None:
        if not self.enabled() or (self._thread and self._thread.is_alive()):
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="phase7-campaign-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)

    def refresh(self, *, now_ms: int | None = None) -> dict[str, Any]:
        timestamp = int(time.time() * 1000) if now_ms is None else int(now_ms)
        with self._lock:
            operations = self.operations.snapshot()
            selected = operations.get("active_campaign") or operations.get("latest_campaign") or {}
            campaign_id = str(selected.get("campaign_id") or "")
            canonical = self.campaign.get(campaign_id) if campaign_id else None
            campaign = dict(canonical or selected or {})
            fills = self.actual_fills(campaign_id)
            metrics = campaign.get("metrics") if isinstance(campaign.get("metrics"), Mapping) else {}
            target = max(
                int((campaign.get("policy") or {}).get("minimum_matched_fills", 20))
                if isinstance(campaign.get("policy"), Mapping)
                else 20,
                20,
            )
            matched = int(metrics.get("matched_fill_count", 0) or 0)
            report_id = str(campaign.get("final_report_id") or "")
            report = self.reports.get(report_id) if report_id else None
            alerts = self._alerts(campaign, operations=operations, fills=fills, matched=matched)
            export_path = str(self._state.get("final_report_path") or "")
            if report and campaign_id:
                export_path = self._export(campaign, report, fills, timestamp) or export_path
            evidence = campaign.get("last_evidence")
            evidence = evidence if isinstance(evidence, Mapping) else {}
            private_stream = evidence.get("private_stream")
            private_stream = dict(private_stream) if isinstance(private_stream, Mapping) else {}
            self._state = {
                "status": str(campaign.get("status") or "idle"),
                "campaign_id": campaign_id,
                "experiment_id": str(campaign.get("experiment_id") or ""),
                "scope": str(campaign.get("scope") or ""),
                "checked_at_ms": timestamp,
                "last_heartbeat_ms": timestamp,
                "cycle_count": int(campaign.get("cycle_count", 0) or 0),
                "progress": {
                    "matched_fills": matched,
                    "target_fills": target,
                    "remaining_fills": max(target - matched, 0),
                    "percent": round(min(matched / target * 100.0, 100.0), 2),
                },
                "actual_fill_count": len(fills),
                "actual_fills": fills[-200:],
                "actual_fee_total": round(sum(float(item["actual_fee"]) for item in fills), 12),
                "alerts": alerts,
                "private_stream": private_stream,
                "final_report_id": report_id,
                "final_report_ready": bool(report),
                "final_report_path": export_path,
                "runtime_flags_changed": False,
                "mainnet_enabled": False,
            }
            self._save()
            return self.snapshot(now_ms=timestamp)

    def snapshot(self, *, now_ms: int | None = None) -> dict[str, Any]:
        timestamp = int(time.time() * 1000) if now_ms is None else int(now_ms)
        with self._lock:
            state = dict(self._state)
            heartbeat = int(state.get("last_heartbeat_ms", 0) or 0)
            age = max((timestamp - heartbeat) / 1000.0, 0.0) if heartbeat else None
            stale = bool(
                state.get("campaign_id")
                and state.get("status") not in _TERMINAL
                and (age is None or age > self.stale_after)
            )
            alerts = list(state.get("alerts") or [])
            if stale:
                alerts.append("monitor_heartbeat_stale")
            return {
                **state,
                "enabled": self.enabled(),
                "worker_running": bool(self._thread and self._thread.is_alive()),
                "heartbeat_age_seconds": round(age, 3) if age is not None else None,
                "heartbeat_stale": stale,
                "alerts": sorted(set(alerts)),
                "private_fill_source": "Bybit private execution evidence",
                "runtime_flags_changed": False,
                "mainnet_enabled": False,
            }

    def actual_fills(self, campaign_id: str) -> list[dict[str, Any]]:
        if not campaign_id:
            return []
        links = {
            str(row.get("order_link_id") or "")
            for row in self.campaign._campaign_records(campaign_id)
            if row.get("order_link_id")
        }
        if not links:
            return []
        snapshot = self.campaign.executions.snapshot()
        source = snapshot.get("managed_fills")
        if not isinstance(source, list):
            source = []
        rows: list[dict[str, Any]] = []
        for item in source:
            if not isinstance(item, Mapping):
                continue
            link = str(item.get("order_link_id") or "")
            if link not in links:
                continue
            exec_id = str(item.get("exec_id") or "")
            if not exec_id:
                continue
            rows.append(
                {
                    "order_link_id": link,
                    "order_id": str(item.get("order_id") or ""),
                    "exec_id": exec_id,
                    "symbol": str(item.get("symbol") or ""),
                    "side": str(item.get("side") or ""),
                    "filled_quantity": _finite(item.get("exec_quantity")),
                    "average_fill_price": _finite(item.get("exec_price")),
                    "executed_value": _finite(item.get("exec_value")),
                    "actual_fee": _finite(item.get("exec_fee")),
                    "fee_currency": str(item.get("fee_currency") or ""),
                    "is_maker": bool(item.get("is_maker")),
                    "first_exec_time_ms": int(item.get("exec_time_ms", 0) or 0),
                    "last_exec_time_ms": int(item.get("exec_time_ms", 0) or 0),
                    "exec_ids": [exec_id],
                    "private_evidence": True,
                }
            )
        return sorted(rows, key=lambda item: (item["last_exec_time_ms"], item["exec_id"]))

    def _alerts(
        self,
        campaign: Mapping[str, Any],
        *,
        operations: Mapping[str, Any],
        fills: list[dict[str, Any]],
        matched: int,
    ) -> list[str]:
        alerts = [str(value) for value in campaign.get("failed_gates", [])]
        metrics = campaign.get("metrics") if isinstance(campaign.get("metrics"), Mapping) else {}
        for name in (
            "orphan_execution_count",
            "duplicate_order_count",
            "unresolved_order_count",
            "unmatched_paper_count",
            "unmatched_testnet_count",
        ):
            if int(metrics.get(name, 0) or 0) > 0:
                alerts.append(name)
        if int(operations.get("active_campaign_count", 0) or 0) > 1:
            alerts.append("multiple_active_campaigns")
        if matched > len(fills):
            alerts.append("private_fill_projection_lags_matched_count")
        evidence = campaign.get("last_evidence")
        evidence = evidence if isinstance(evidence, Mapping) else {}
        private_stream = evidence.get("private_stream")
        if isinstance(private_stream, Mapping) and private_stream and not private_stream.get("ready"):
            alerts.append("private_stream_not_ready")
        return sorted(set(alerts))

    def _export(
        self,
        campaign: Mapping[str, Any],
        report: Mapping[str, Any],
        fills: list[dict[str, Any]],
        timestamp: int,
    ) -> str:
        try:
            self.report_directory.mkdir(parents=True, exist_ok=True)
            target = self.report_directory / f"{campaign['campaign_id']}.json"
            payload = {
                "schema_version": 1,
                "campaign": dict(campaign),
                "actual_private_fills": fills,
                "final_promotion_report": dict(report),
                "exported_at_ms": timestamp,
                "mainnet_enabled": False,
            }
            temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False),
                encoding="utf-8",
            )
            os.replace(temporary, target)
            return str(target)
        except OSError:
            return ""

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.refresh()
            except Exception as exc:
                with self._lock:
                    self._state = {
                        **self._state,
                        "status": "degraded",
                        "last_heartbeat_ms": int(time.time() * 1000),
                        "alerts": sorted(
                            set([*self._state.get("alerts", []), "monitor_refresh_error"])
                        ),
                        "last_error": f"{type(exc).__name__}: {exc}",
                    }
                    self._save()

    def _load(self) -> dict[str, Any]:
        current = self.database.get_json(_STATE_NAMESPACE, "current")
        if current and isinstance(current.get("value"), Mapping):
            return dict(current["value"])
        return {
            "status": "idle",
            "campaign_id": "",
            "last_heartbeat_ms": 0,
            "alerts": [],
            "actual_fills": [],
            "runtime_flags_changed": False,
            "mainnet_enabled": False,
        }

    def _save(self) -> None:
        current = self.database.get_json(_STATE_NAMESPACE, "current")
        self.database.put_json(
            _STATE_NAMESPACE,
            "current",
            dict(self._state),
            expected_version=int(current["version"]) if current else 0,
        )


def _finite(value: Any) -> float:
    try:
        parsed = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return parsed if math.isfinite(parsed) else 0.0


def _bounded_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        parsed = default
    if not math.isfinite(parsed):
        parsed = default
    return min(max(parsed, minimum), maximum)


__all__ = ["Phase7CampaignMonitor"]
