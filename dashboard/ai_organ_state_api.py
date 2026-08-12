"""Runtime heartbeat and evidence API for the nine canonical SharipovAI organs.

This monitor does not create new AI components. It observes the existing
runtime, records evidence in the shared database and reports degraded/blocked
states honestly when a dependency is absent, stale or unsafe.
"""
from __future__ import annotations

import importlib.util
import math
import os
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any, Callable

from fastapi import FastAPI

from ai_architecture_registry import CANONICAL_AI_ORGANS
from exchange_connector.bybit_execution import effective_testnet_notional_cap_usdt
from risk_engine import CanonicalRiskService
from storage import ProjectDatabase, list_json_items


@dataclass(frozen=True, slots=True)
class OrganRuntimeState:
    organ_id: str
    status: str
    responsibility: str
    evidence: tuple[str, ...]
    blockers: tuple[str, ...]
    checked_at_ms: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AIOrganRuntimeMonitor:
    def __init__(
        self,
        app: FastAPI,
        database: ProjectDatabase,
        *,
        clock_ms: Callable[[], int] | None = None,
    ) -> None:
        self.app = app
        self.database = database
        self.database.initialize()
        self.clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        self.interval_seconds = _bounded_float("AI_ORGAN_HEARTBEAT_SECONDS", 30.0, 10.0, 300.0)
        self.evidence_max_age_seconds = _bounded_float(
            "AI_ORGAN_EVIDENCE_MAX_AGE_SECONDS", 300.0, 30.0, 3600.0
        )
        self.risk_service = CanonicalRiskService()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._last_error = ""

    def start(self) -> None:
        self.refresh()
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="ai-organ-runtime-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=2.0)

    def refresh(self) -> dict[str, Any]:
        states = self._evaluate()
        now = self.clock_ms()
        for state in states:
            payload = state.to_dict()
            self.database.put_json("ai_organ_runtime", state.organ_id, payload)
            setter = getattr(self.database, "set_ai_organ_state", None)
            if callable(setter):
                try:
                    setter(state.organ_id, payload)
                except TypeError:
                    try:
                        setter(state.organ_id, state.status, payload)
                    except TypeError:
                        pass
        summary = _summary(states, now_ms=now)
        self.database.put_json("system_runtime", "ai_organs", summary)
        with self._lock:
            self._last_error = ""
        return summary

    def snapshot(self) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        for organ in CANONICAL_AI_ORGANS:
            current = self.database.get_json("ai_organ_runtime", organ.id)
            if current is not None and isinstance(current.get("value"), dict):
                rows.append(dict(current["value"]))
        if len(rows) != len(CANONICAL_AI_ORGANS):
            return self.refresh()
        with self._lock:
            last_error = self._last_error
        return {
            **_summary([_state_from_dict(item) for item in rows], now_ms=self.clock_ms()),
            "monitor_running": bool(self._thread and self._thread.is_alive()),
            "last_error": last_error,
            "evidence_max_age_seconds": self.evidence_max_age_seconds,
        }

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            try:
                self.refresh()
            except Exception as exc:
                with self._lock:
                    self._last_error = f"{type(exc).__name__}: {exc}"
                try:
                    self.database.append_event(
                        "system_runtime",
                        "ai_organ_monitor",
                        "refresh_error",
                        {"error": self._last_error, "checked_at_ms": self.clock_ms()},
                    )
                except Exception:
                    continue

    def _evaluate(self) -> list[OrganRuntimeState]:
        now = self.clock_ms()
        if now <= 0:
            raise ValueError("clock must return a positive timestamp")
        responsibility = {organ.id: organ.responsibility for organ in CANONICAL_AI_ORGANS}
        return [
            self._state("general_controller", responsibility, now, *self._general_controller()),
            self._state("market_intelligence", responsibility, now, *self._market_intelligence()),
            self._state("news_intelligence", responsibility, now, *self._news_intelligence()),
            self._state("risk_engine", responsibility, now, *self._risk_engine()),
            self._state("portfolio_engine", responsibility, now, *self._portfolio_engine()),
            self._state("virtual_execution", responsibility, now, *self._virtual_execution()),
            self._state("decision_quality", responsibility, now, *self._decision_quality()),
            self._state("learning_engine", responsibility, now, *self._learning_engine()),
            self._state("security_guard", responsibility, now, *self._security_guard()),
        ]

    @staticmethod
    def _state(
        organ_id: str,
        responsibilities: dict[str, str],
        now: int,
        evidence: list[str],
        blockers: list[str],
    ) -> OrganRuntimeState:
        if blockers:
            status = "blocked" if any(item.startswith("critical:") for item in blockers) else "degraded"
        else:
            status = "healthy"
        return OrganRuntimeState(
            organ_id=organ_id,
            status=status,
            responsibility=responsibilities[organ_id],
            evidence=tuple(evidence),
            blockers=tuple(blockers),
            checked_at_ms=now,
        )

    def _general_controller(self) -> tuple[list[str], list[str]]:
        evidence, blockers = [], []
        if getattr(self.app.state, "control_plane_api_installed", False):
            evidence.append("control_plane_api_installed")
        else:
            blockers.append("control plane API is not installed")
        runtime_database = getattr(self.app.state, "project_database", None)
        if _same_database(runtime_database, self.database):
            evidence.append("shared_project_database")
        else:
            blockers.append("critical: runtime components do not share the canonical database")
        return evidence, blockers

    def _market_intelligence(self) -> tuple[list[str], list[str]]:
        evidence, blockers = [], []
        worker = getattr(self.app.state, "bybit_websocket_worker", None)
        if worker is None:
            blockers.append("critical: canonical public market worker is absent")
            return evidence, blockers
        try:
            status = worker.status()
        except Exception as exc:
            blockers.append(f"market worker status failed: {type(exc).__name__}: {exc}")
            return evidence, blockers
        evidence.append("canonical_bybit_public_worker")
        if status.get("database_backed") is True:
            evidence.append("verified_quotes_persisted")
        else:
            blockers.append("market quotes are not confirmed database-backed")
        if _truthy_default("MARKET_STREAM_ENABLED", True) and status.get("verified") is not True:
            blockers.append("configured market stream is not currently verified")
        if status.get("worker_running") is True:
            evidence.append("market_worker_running")
        elif _truthy_default("MARKET_STREAM_ENABLED", True):
            blockers.append("canonical market worker thread is not running")
        return evidence, blockers

    def _news_intelligence(self) -> tuple[list[str], list[str]]:
        evidence, blockers = [], []
        network = getattr(self.app.state, "news_agent_network", None)
        if network is None:
            blockers.append("critical: News Intelligence network is absent")
            return evidence, blockers
        evidence.append(f"source_agents={len(getattr(network, 'agents', []))}")
        if _same_database(getattr(network, "database", None), self.database):
            evidence.append("news_memory_database_backed")
        else:
            blockers.append("News Intelligence is not using the canonical database")
        try:
            snapshot = network.snapshot()
        except Exception as exc:
            blockers.append(f"news runtime status failed: {type(exc).__name__}: {exc}")
            return evidence, blockers
        if snapshot.get("status") == "running":
            evidence.append("news_worker_running")
        else:
            blockers.append("News Intelligence worker is not running")
        last_cycle = int(snapshot.get("last_cycle_at_ms") or 0)
        self._append_freshness(evidence, blockers, "news_cycle", last_cycle)
        if snapshot.get("last_error"):
            blockers.append(f"News Intelligence last cycle error: {snapshot.get('last_error')}")
        return evidence, blockers

    def _risk_engine(self) -> tuple[list[str], list[str]]:
        evidence, blockers = [], []
        try:
            probe = self.risk_service.evaluate(
                {"market_data_verified": False, "exchange_ok": False},
                profile="health_probe",
            )
        except Exception as exc:
            blockers.append(f"critical: canonical risk service failed: {type(exc).__name__}: {exc}")
            return evidence, blockers
        if not probe.allowed_virtual and "market_data_unverified" in probe.hard_blocks:
            evidence.append("canonical_risk_service_fail_closed")
        else:
            blockers.append("critical: canonical risk service did not fail closed")
        try:
            configured_notional = float(os.getenv("EXECUTION_MAX_NOTIONAL_USDT", "25"))
            if math.isfinite(configured_notional) and configured_notional > 0:
                effective_notional = effective_testnet_notional_cap_usdt()
                evidence.append(f"execution_notional_cap={effective_notional:g}")
                if effective_notional != configured_notional:
                    evidence.append("execution_notional_config_clamped")
            else:
                blockers.append("critical: execution notional cap is invalid")
        except ValueError:
            blockers.append("critical: execution notional cap is invalid")
        self._append_latest_json(evidence, blockers, "risk_assessments", "risk_assessment")
        return evidence, blockers

    def _portfolio_engine(self) -> tuple[list[str], list[str]]:
        evidence, blockers = [], []
        loop = getattr(self.app.state, "autonomous_paper_loop", None)
        if loop is None:
            blockers.append("portfolio/paper account runtime is absent")
            return evidence, blockers
        if _same_database(getattr(loop, "database", None), self.database):
            evidence.append("paper_portfolio_database_backed")
        else:
            blockers.append("portfolio state is not using the canonical database")
        self._append_latest_json(evidence, blockers, "portfolio_snapshots", "portfolio_snapshot")
        return evidence, blockers

    def _virtual_execution(self) -> tuple[list[str], list[str]]:
        evidence, blockers = [], []
        loop = getattr(self.app.state, "autonomous_paper_loop", None)
        if loop is None:
            blockers.append("virtual execution runtime is absent")
            return evidence, blockers
        evidence.append("canonical_council_paper_runtime")
        thread = getattr(loop, "_thread", None)
        configured = _truthy_default("AUTONOMOUS_PAPER_ENABLED", True)
        running = bool(thread and thread.is_alive())
        if configured and running:
            evidence.append("paper_execution_worker_running")
        elif configured:
            blockers.append("canonical paper execution worker is not running")
        else:
            evidence.append("paper_execution_disabled_by_policy")
        try:
            snapshot = loop.snapshot()
        except Exception as exc:
            blockers.append(f"virtual execution snapshot failed: {type(exc).__name__}: {exc}")
            return evidence, blockers
        if snapshot.get("database_backed") is True:
            evidence.append("paper_execution_database_backed")
        else:
            blockers.append("virtual execution state is not database-backed")
        if snapshot.get("decision_mode") == "CANONICAL_COUNCIL_REQUIRED":
            evidence.append("canonical_council_authorization_required")
        else:
            blockers.append("virtual execution does not require canonical council authorization")
        return evidence, blockers

    def _decision_quality(self) -> tuple[list[str], list[str]]:
        evidence, blockers = [], []
        for module_name in ("trading_candidate", "exchange_connector.preview_candidate_bridge"):
            if importlib.util.find_spec(module_name) is not None:
                evidence.append(module_name)
            else:
                blockers.append(f"critical: decision evidence module missing: {module_name}")
        try:
            events = self.database.list_events(
                "decision_quality", entity_type="decision_assessment", limit=1
            )
        except Exception as exc:
            blockers.append(f"decision evidence query failed: {type(exc).__name__}: {exc}")
        else:
            if not events:
                blockers.append("no persisted Decision Quality assessment evidence")
            else:
                self._append_freshness(
                    evidence,
                    blockers,
                    "decision_assessment",
                    int(events[0].get("created_at_ms") or 0),
                )
        return evidence, blockers

    def _learning_engine(self) -> tuple[list[str], list[str]]:
        evidence, blockers = [], []
        supervisor = getattr(self.app.state, "self_learning_supervisor", None)
        if supervisor is not None:
            try:
                status = supervisor.status()
            except Exception as exc:
                blockers.append(f"learning supervisor status failed: {type(exc).__name__}: {exc}")
            else:
                if status.get("enabled") is True and status.get("worker_running") is True:
                    evidence.append("self_learning_worker_running")
                elif status.get("enabled") is True:
                    blockers.append("self-learning supervisor is enabled but not running")
                else:
                    evidence.append("self_learning_disabled_by_policy")
        current = self.database.get_json("self_learning_supervisor_state", "current")
        if current is None:
            blockers.append("no persisted self-learning supervisor evidence")
        else:
            self._append_freshness(
                evidence,
                blockers,
                "self_learning_state",
                int(current.get("updated_at_ms") or 0),
                maximum=max(self.evidence_max_age_seconds, 180.0),
            )
            value = current.get("value") if isinstance(current.get("value"), dict) else {}
            evidence.append(f"verified_outcomes={value.get('learning_summary', {}).get('verified_outcome_count', 0)}")
            if value.get("status") in {"error", "blocked"}:
                blockers.append(f"self-learning supervisor status={value.get('status')}")
        return evidence, blockers

    def _security_guard(self) -> tuple[list[str], list[str]]:
        evidence, blockers = [], []
        if getattr(self.app.state, "global_auth_guard_installed", False):
            evidence.append("global_auth_guard")
        else:
            blockers.append("critical: global authentication guard is absent")
        if _truthy("EXECUTION_KILL_SWITCH"):
            evidence.append("execution_kill_switch_active")
        else:
            blockers.append("critical: execution kill switch is not active")
        if _truthy("TESTNET_EXECUTION_ENABLED") or _truthy("EXCHANGE_LIVE_TRADING_ENABLED"):
            blockers.append("critical: financial execution is enabled during protected runtime")
        else:
            evidence.append("testnet_and_live_execution_locked")
        if _truthy("BYBIT_ALLOW_LEGACY_EXCHANGE_CREDENTIALS"):
            blockers.append("critical: legacy exchange credential fallback is enabled")
        else:
            evidence.append("legacy_exchange_credentials_blocked")
        return evidence, blockers

    def _append_latest_json(
        self,
        evidence: list[str],
        blockers: list[str],
        namespace: str,
        label: str,
    ) -> None:
        try:
            rows = list_json_items(self.database, namespace, limit=1, newest_first=True)
        except Exception as exc:
            blockers.append(f"{label} evidence query failed: {type(exc).__name__}: {exc}")
            return
        if not rows:
            blockers.append(f"no persisted {label} evidence")
            return
        self._append_freshness(
            evidence,
            blockers,
            label,
            int(rows[0].get("updated_at_ms") or 0),
        )

    def _append_freshness(
        self,
        evidence: list[str],
        blockers: list[str],
        label: str,
        timestamp_ms: int,
        *,
        maximum: float | None = None,
    ) -> None:
        if timestamp_ms <= 0:
            blockers.append(f"{label} timestamp is missing")
            return
        age = max(0.0, (self.clock_ms() - timestamp_ms) / 1000.0)
        limit = self.evidence_max_age_seconds if maximum is None else float(maximum)
        evidence.append(f"{label}_age_seconds={age:.3f}")
        if age > limit:
            blockers.append(f"{label} evidence is stale ({age:.1f}s > {limit:.1f}s)")


def install_ai_organ_state_api(app: FastAPI) -> None:
    if getattr(app.state, "ai_organ_state_api_installed", False):
        return
    app.state.ai_organ_state_api_installed = True
    database = getattr(app.state, "project_database", None)
    if not isinstance(database, ProjectDatabase):
        raise RuntimeError("ProjectDatabase must be installed before AI organ monitor")
    monitor = AIOrganRuntimeMonitor(app, database)
    app.state.ai_organ_runtime_monitor = monitor
    app.add_event_handler("startup", monitor.start)
    app.add_event_handler("shutdown", monitor.stop)

    @app.get("/api/system/ai-organs")
    def ai_organs_status() -> dict[str, Any]:
        return monitor.snapshot()

    @app.post("/api/system/ai-organs/refresh")
    def refresh_ai_organs() -> dict[str, Any]:
        return monitor.refresh()


def _summary(states: list[OrganRuntimeState], *, now_ms: int) -> dict[str, Any]:
    counts = {"healthy": 0, "degraded": 0, "blocked": 0}
    for state in states:
        counts[state.status] = counts.get(state.status, 0) + 1
    return {
        "status": "healthy" if counts["blocked"] == 0 and counts["degraded"] == 0 else "degraded" if counts["blocked"] == 0 else "blocked",
        "checked_at_ms": now_ms,
        "organ_count": len(states),
        "counts": counts,
        "organs": [state.to_dict() for state in states],
        "database_backed": True,
    }


def _state_from_dict(value: dict[str, Any]) -> OrganRuntimeState:
    return OrganRuntimeState(
        organ_id=str(value.get("organ_id", "")),
        status=str(value.get("status", "blocked")),
        responsibility=str(value.get("responsibility", "")),
        evidence=tuple(str(item) for item in value.get("evidence", [])),
        blockers=tuple(str(item) for item in value.get("blockers", [])),
        checked_at_ms=int(value.get("checked_at_ms", 0)),
    )


def _same_database(left: Any, right: Any) -> bool:
    left_dsn = str(getattr(left, "dsn", "") or "")
    right_dsn = str(getattr(right, "dsn", "") or "")
    return bool(left_dsn and right_dsn and left_dsn == right_dsn)


def _truthy(name: str) -> bool:
    return os.getenv(name, "0").strip().lower() in {"1", "true", "yes", "on"}


def _truthy_default(name: str, default: bool) -> bool:
    fallback = "1" if default else "0"
    return os.getenv(name, fallback).strip().lower() in {"1", "true", "yes", "on"}


def _bounded_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    if not math.isfinite(value):
        return default
    return min(max(value, minimum), maximum)


__all__ = ["AIOrganRuntimeMonitor", "OrganRuntimeState", "install_ai_organ_state_api"]
