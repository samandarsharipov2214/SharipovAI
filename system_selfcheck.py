"""Mandatory post-change self-checks for SharipovAI."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from architecture_registry import architecture_audit
from general_controller import GeneralController
from memory.unified_memory import UnifiedMemory
from portfolio_engine import PortfolioEngine, PortfolioInput, Position
from risk_engine import RiskEngine, RiskInput


def run_system_selfcheck() -> dict[str, Any]:
    checks = {
        "architecture": _architecture_check(),
        "controller": _controller_check(),
        "memory": _memory_check(),
        "risk": _risk_check(),
        "portfolio": _portfolio_check(),
    }
    return {
        "status": "ok" if all(item["ok"] for item in checks.values()) else "failed",
        "checks": checks,
        "policy": "A change is not ready for main while any mandatory check fails.",
    }


def _architecture_check() -> dict[str, Any]:
    audit = architecture_audit()
    return {"ok": audit["status"] == "ok", "details": audit}


def _controller_check() -> dict[str, Any]:
    controller = GeneralController()
    known = controller.route("market_analysis")
    unknown = controller.route("unregistered_new_ai_capability")
    ok = known.allowed and known.selected_owner == "market_agent" and not unknown.allowed
    return {"ok": ok, "details": {"known": known, "unknown": unknown}}


def _memory_check() -> dict[str, Any]:
    with TemporaryDirectory() as directory:
        memory = UnifiedMemory(Path(directory) / "memory.json")
        first = memory.put("project", "architecture", {"version": "2.0"}, source="selfcheck")
        second = memory.put("project", "architecture", {"version": "2.1"}, source="selfcheck")
        loaded = memory.get("project", "architecture")
        ok = first.version == 1 and second.version == 2 and loaded is not None and loaded.value["version"] == "2.1"
        return {"ok": ok, "details": memory.health()}


def _risk_check() -> dict[str, Any]:
    engine = RiskEngine()
    safe = engine.evaluate(RiskInput(1, 10, 5, 10, 90, 10))
    critical = engine.evaluate(RiskInput(95, 100, 100, 100, 0, 100))
    return {"ok": safe.allowed and not critical.allowed, "details": {"safe": safe, "critical": critical}}


def _portfolio_check() -> dict[str, Any]:
    output = PortfolioEngine().evaluate(
        PortfolioInput(cash=5000.0, positions=[Position("BTCUSDT", 0.1, 40000.0, 50000.0)])
    )
    return {
        "ok": output.total_value == 10000.0 and output.positions_count == 1 and output.exposure_percent == 50.0,
        "details": output,
    }
