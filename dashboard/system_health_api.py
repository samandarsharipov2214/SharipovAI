"""Unified read-only health center for the existing SharipovAI runtime.

The health center aggregates evidence from components already present in the
application. It does not create another AI organ and it never restarts or
activates financial execution. Recovery actions are recommendations only.
"""
from __future__ import annotations

import math
import os
import shutil
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI


@dataclass(frozen=True, slots=True)
class ComponentHealth:
    component: str
    status: str
    evidence: tuple[str, ...]
    blockers: tuple[str, ...]
    recovery: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SystemHealthCenter:
    """Aggregate runtime health without duplicating component ownership."""

    def __init__(self, app: FastAPI, *, clock: Callable[[], float] | None = None) -> None:
        self.app = app
        self.clock = clock or time.time
        self.data_dir = Path(os.getenv("SHARIPOVAI_DATA_DIR", "data"))
        self.disk_warning_percent = _bounded_float("SYSTEM_DISK_WARNING_PERCENT", 85.0, 50.0, 99.0)
        self.disk_block_percent = _bounded_float("SYSTEM_DISK_BLOCK_PERCENT", 95.0, 60.0, 100.0)

    def snapshot(self) -> dict[str, Any]:
        checked_at_ms = int(self.clock() * 1000)
        components = [
            self._database(),
            self._ai_organs(),
            self._market(),
            self._news(),
            self._telegram(),
            self._security(),
            self._storage(),
            self._backup(),
        ]
        counts = {"healthy": 0, "degraded": 0, "blocked": 0}
        for item in components:
            counts[item.status] = counts.get(item.status, 0) + 1
        overall = "blocked" if counts["blocked"] else "degraded" if counts["degraded"] else "healthy"
        payload = {
            "status": overall,
            "checked_at_ms": checked_at_ms,
            "counts": counts,
            "components": [item.to_dict() for item in components],
            "safe_mode": overall == "blocked",
            "automatic_financial_recovery": False,
            "automatic_failover": False,
        }
        database = getattr(self.app.state, "project_database", None)
        put_json = getattr(database, "put_json", None)
        if callable(put_json):
            try:
                put_json("system_runtime", "health_center", payload)
            except Exception:
                pass
        return payload

    def _database(self) -> ComponentHealth:
        database = getattr(self.app.state, "project_database", None)
        if database is None:
            return _component("database", [], ["critical: canonical ProjectDatabase is absent"], ["restore database configuration"])
        try:
            health = database.health()
        except Exception as exc:
            return _component("database", [], [f"critical: database health failed: {type(exc).__name__}: {exc}"], ["check DATABASE_URL and database availability"])
        if health.get("status") != "ok":
            return _component("database", [], [f"critical: database unavailable: {health.get('error', 'unknown error')}"], ["reconnect database", "restore verified backup if corruption is confirmed"])
        return _component("database", [f"backend={health.get('backend', 'unknown')}", "schema_ready"], [], [])

    def _ai_organs(self) -> ComponentHealth:
        monitor = getattr(self.app.state, "ai_organ_runtime_monitor", None)
        if monitor is None:
            return _component("ai_organs", [], ["AI organ runtime monitor is absent"], ["install existing AI organ monitor"])
        try:
            snapshot = monitor.snapshot()
        except Exception as exc:
            return _component("ai_organs", [], [f"AI organ monitor failed: {type(exc).__name__}: {exc}"], ["refresh AI organ monitor"])
        status = str(snapshot.get("status", "blocked"))
        blockers = [] if status == "healthy" else [f"AI organs status={status}"]
        if snapshot.get("monitor_running") is False:
            blockers.append("AI organ heartbeat thread is not running")
        return _component("ai_organs", [f"organ_count={snapshot.get('organ_count', 0)}", f"status={status}"], blockers, ["inspect /api/system/ai-organs"] if blockers else [])

    def _market(self) -> ComponentHealth:
        worker = getattr(self.app.state, "bybit_websocket_worker", None)
        if worker is None:
            return _component("market", [], ["canonical market worker is absent"], ["restart application runtime"])
        try:
            status = worker.status()
        except Exception as exc:
            return _component("market", [], [f"market status failed: {type(exc).__name__}: {exc}"], ["reconnect public market stream"])
        evidence = ["canonical_worker_present"]
        blockers: list[str] = []
        if status.get("database_backed") is True:
            evidence.append("database_backed_quotes")
        else:
            blockers.append("market quotes are not confirmed database-backed")
        if _truthy("MARKET_STREAM_ENABLED") and status.get("verified") is not True:
            blockers.append("configured market stream is not verified")
        return _component("market", evidence, blockers, ["reconnect public market stream"] if blockers else [])

    def _news(self) -> ComponentHealth:
        network = getattr(self.app.state, "news_agent_network", None)
        if network is None:
            return _component("news", [], ["News Intelligence network is absent"], ["restart news runtime"])
        agents = len(getattr(network, "agents", []))
        database = getattr(self.app.state, "project_database", None)
        blockers = [] if getattr(network, "database", None) is database else ["news memory is not using canonical database"]
        return _component("news", [f"source_agents={agents}"], blockers, ["rebind NewsHub to ProjectDatabase"] if blockers else [])

    def _telegram(self) -> ComponentHealth:
        token = bool(os.getenv("BOT_TOKEN", "").strip())
        webapp = bool(os.getenv("WEBAPP_URL", "").strip() or os.getenv("TELEGRAM_WEBAPP_URL", "").strip())
        evidence: list[str] = []
        blockers: list[str] = []
        if token:
            evidence.append("bot_token_configured")
        else:
            blockers.append("Telegram bot token is not configured")
        if webapp:
            evidence.append("webapp_url_configured")
        else:
            blockers.append("Telegram webapp URL is not configured")
        runtime = getattr(self.app.state, "telegram_health", None)
        if isinstance(runtime, dict):
            evidence.append(f"runtime_status={runtime.get('status', 'unknown')}")
            if runtime.get("status") in {"error", "blocked"}:
                blockers.append("Telegram runtime reports an error")
        return _component("telegram", evidence, blockers, ["restart Telegram worker", "verify Telegram credentials"] if blockers else [])

    def _security(self) -> ComponentHealth:
        evidence: list[str] = []
        blockers: list[str] = []
        if getattr(self.app.state, "global_auth_guard_installed", False):
            evidence.append("global_auth_guard")
        else:
            blockers.append("critical: global auth guard is absent")
        if _truthy("EXECUTION_KILL_SWITCH"):
            evidence.append("execution_kill_switch_active")
        else:
            blockers.append("critical: execution kill switch is disabled")
        if _truthy("EXCHANGE_LIVE_TRADING_ENABLED") or _truthy("TESTNET_EXECUTION_ENABLED"):
            blockers.append("critical: financial execution is enabled")
        else:
            evidence.append("financial_execution_locked")
        return _component("security", evidence, blockers, ["enter safe mode", "restore protected execution flags"] if blockers else [])

    def _storage(self) -> ComponentHealth:
        target = self.data_dir if self.data_dir.exists() else self.data_dir.parent
        try:
            usage = shutil.disk_usage(target)
        except OSError as exc:
            return _component("storage", [], [f"disk usage unavailable: {exc}"], ["inspect filesystem"])
        used_percent = (usage.used / usage.total * 100.0) if usage.total else 100.0
        evidence = [f"used_percent={used_percent:.1f}", f"free_bytes={usage.free}"]
        if used_percent >= self.disk_block_percent:
            return _component("storage", evidence, ["critical: disk usage exceeds block threshold"], ["free disk space", "rotate logs and backups"])
        if used_percent >= self.disk_warning_percent:
            return _component("storage", evidence, ["disk usage exceeds warning threshold"], ["rotate logs and backups"])
        return _component("storage", evidence, [], [])

    def _backup(self) -> ComponentHealth:
        candidates = [
            self.data_dir.parent / "deploy" / "vps" / "backups" / "latest.tar.gz",
            Path("deploy/vps/backups/latest.tar.gz"),
            Path("runtime/remote_backups/current/manifest.json"),
        ]
        existing = [path for path in candidates if path.exists()]
        if not existing:
            return _component("backup", [], ["verified backup evidence is not visible to this runtime"], ["run configured VPS backup job"])
        newest = max(existing, key=lambda item: item.stat().st_mtime)
        age = max(0.0, self.clock() - newest.stat().st_mtime)
        max_age = _bounded_float("SYSTEM_BACKUP_MAX_AGE_SECONDS", 7200.0, 300.0, 604800.0)
        evidence = [f"latest={newest}", f"age_seconds={int(age)}"]
        if age > max_age:
            return _component("backup", evidence, ["backup evidence is stale"], ["run verified backup immediately"])
        return _component("backup", evidence, [], [])


def install_system_health_api(app: FastAPI) -> None:
    if getattr(app.state, "system_health_api_installed", False):
        return
    app.state.system_health_api_installed = True
    center = SystemHealthCenter(app)
    app.state.system_health_center = center

    @app.get("/api/system/health")
    def system_health() -> dict[str, Any]:
        return center.snapshot()

    @app.get("/api/system/recovery-plan")
    def recovery_plan() -> dict[str, Any]:
        snapshot = center.snapshot()
        actions = []
        for component in snapshot["components"]:
            for action in component.get("recovery", []):
                actions.append({"component": component["component"], "action": action, "automatic": False})
        return {
            "status": snapshot["status"],
            "safe_mode": snapshot["safe_mode"],
            "automatic_financial_recovery": False,
            "automatic_failover": False,
            "actions": actions,
        }


def _component(name: str, evidence: list[str], blockers: list[str], recovery: list[str]) -> ComponentHealth:
    critical = any(item.startswith("critical:") for item in blockers)
    status = "blocked" if critical else "degraded" if blockers else "healthy"
    return ComponentHealth(name, status, tuple(evidence), tuple(blockers), tuple(recovery))


def _truthy(name: str) -> bool:
    return os.getenv(name, "0").strip().lower() in {"1", "true", "yes", "on"}


def _bounded_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    if not math.isfinite(value) or value < minimum or value > maximum:
        return default
    return value


__all__ = ["ComponentHealth", "SystemHealthCenter", "install_system_health_api"]
