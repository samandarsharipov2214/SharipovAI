from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard.ai_organ_state_safe_api import (
    SafeAIOrganRuntimeMonitor,
    install_ai_organ_state_api,
)
from storage import ProjectDatabase


class Worker:
    def status(self):
        return {
            "connected": False,
            "verified": False,
            "database_backed": True,
            "worker_running": False,
        }


class Network:
    def __init__(self, database):
        self.database = database
        self.agents = [object()] * 12


class Loop:
    def __init__(self, database):
        self.database = database


def database(tmp_path: Path) -> ProjectDatabase:
    value = ProjectDatabase(f"sqlite:///{tmp_path / 'shared.db'}")
    value.initialize()
    return value


def configure_safe(monkeypatch) -> None:
    monkeypatch.setenv("EXECUTION_KILL_SWITCH", "1")
    monkeypatch.setenv("TESTNET_EXECUTION_ENABLED", "0")
    monkeypatch.setenv("EXCHANGE_LIVE_TRADING_ENABLED", "0")
    monkeypatch.setenv("BYBIT_ALLOW_LEGACY_EXCHANGE_CREDENTIALS", "0")
    monkeypatch.setenv("AUTONOMOUS_PAPER_ENABLED", "1")
    monkeypatch.setenv("MARKET_STREAM_ENABLED", "0")
    monkeypatch.setenv("EXECUTION_MAX_NOTIONAL_USDT", "25")


def prepared_app(db: ProjectDatabase) -> FastAPI:
    app = FastAPI()
    app.state.project_database = db
    app.state.control_plane_api_installed = True
    app.state.bybit_websocket_worker = Worker()
    app.state.news_agent_network = Network(db)
    app.state.autonomous_paper_loop = Loop(db)
    app.state.global_auth_guard_installed = True
    return app


def test_monitor_persists_exactly_nine_canonical_organs(tmp_path, monkeypatch) -> None:
    configure_safe(monkeypatch)
    db = database(tmp_path)
    monitor = SafeAIOrganRuntimeMonitor(prepared_app(db), db, clock_ms=lambda: 1_000)
    result = monitor.refresh()
    assert result["organ_count"] == 9
    assert {item["organ_id"] for item in result["organs"]} == {
        "general_controller",
        "market_intelligence",
        "news_intelligence",
        "risk_engine",
        "portfolio_engine",
        "virtual_execution",
        "decision_quality",
        "learning_engine",
        "security_guard",
    }
    assert result["database_backed"] is True
    for organ_id in {item["organ_id"] for item in result["organs"]}:
        stored = db.get_json("ai_organ_runtime", organ_id)
        assert stored is not None
        assert stored["value"]["checked_at_ms"] == 1_000


def test_monitor_reports_degraded_instead_of_inventing_health(tmp_path, monkeypatch) -> None:
    configure_safe(monkeypatch)
    db = database(tmp_path)
    app = prepared_app(db)
    del app.state.news_agent_network
    result = SafeAIOrganRuntimeMonitor(app, db, clock_ms=lambda: 2_000).refresh()
    news = next(item for item in result["organs"] if item["organ_id"] == "news_intelligence")
    assert news["status"] == "blocked"
    assert any("absent" in item for item in news["blockers"])
    assert result["status"] == "blocked"


def test_security_guard_blocks_unsafe_execution_runtime(tmp_path, monkeypatch) -> None:
    configure_safe(monkeypatch)
    monkeypatch.setenv("EXECUTION_KILL_SWITCH", "0")
    monkeypatch.setenv("EXCHANGE_LIVE_TRADING_ENABLED", "1")
    monkeypatch.setenv("BYBIT_ALLOW_LEGACY_EXCHANGE_CREDENTIALS", "1")
    db = database(tmp_path)
    result = SafeAIOrganRuntimeMonitor(prepared_app(db), db, clock_ms=lambda: 3_000).refresh()
    security = next(item for item in result["organs"] if item["organ_id"] == "security_guard")
    assert security["status"] == "blocked"
    assert len(security["blockers"]) >= 3


def test_snapshot_recovers_persisted_organ_state_after_restart(tmp_path, monkeypatch) -> None:
    configure_safe(monkeypatch)
    db = database(tmp_path)
    app = prepared_app(db)
    SafeAIOrganRuntimeMonitor(app, db, clock_ms=lambda: 4_000).refresh()
    restored = SafeAIOrganRuntimeMonitor(app, db, clock_ms=lambda: 5_000).snapshot()
    assert restored["organ_count"] == 9
    assert all(item["checked_at_ms"] == 4_000 for item in restored["organs"])


def test_installer_requires_shared_database_and_registers_routes(tmp_path, monkeypatch) -> None:
    configure_safe(monkeypatch)
    app = FastAPI()
    try:
        install_ai_organ_state_api(app)
    except RuntimeError as exc:
        assert "ProjectDatabase" in str(exc)
    else:
        raise AssertionError("installer must fail without canonical database")

    db = database(tmp_path)
    app = prepared_app(db)
    install_ai_organ_state_api(app)
    paths = {route.path for route in app.routes}
    assert "/api/system/ai-organs" in paths
    assert "/api/system/ai-organs/refresh" in paths
    with TestClient(app) as client:
        response = client.get("/api/system/ai-organs")
        assert response.status_code == 200
        assert response.json()["organ_count"] == 9
