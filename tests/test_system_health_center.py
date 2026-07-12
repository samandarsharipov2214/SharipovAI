from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard.system_health_api import SystemHealthCenter, install_system_health_api


class FakeDatabase:
    def __init__(self) -> None:
        self.saved: dict[tuple[str, str], object] = {}

    def health(self) -> dict[str, object]:
        return {"status": "ok", "backend": "sqlite", "schema_version": 1}

    def put_json(self, namespace: str, key: str, value: object) -> int:
        self.saved[(namespace, key)] = value
        return 1


class FakeMonitor:
    def snapshot(self) -> dict[str, object]:
        return {"status": "healthy", "organ_count": 9, "monitor_running": True}


class FakeMarket:
    def status(self) -> dict[str, object]:
        return {"verified": True, "database_backed": True}


class FakeNews:
    def __init__(self, database: FakeDatabase) -> None:
        self.database = database
        self.agents = [object(), object()]


def healthy_app(tmp_path: Path, monkeypatch) -> FastAPI:
    monkeypatch.chdir(tmp_path)
    data = tmp_path / "data"
    data.mkdir()
    backup = tmp_path / "runtime" / "remote_backups" / "current" / "manifest.json"
    backup.parent.mkdir(parents=True)
    backup.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("SHARIPOVAI_DATA_DIR", str(data))
    monkeypatch.setenv("BOT_TOKEN", "configured")
    monkeypatch.setenv("WEBAPP_URL", "https://example.test")
    monkeypatch.setenv("EXECUTION_KILL_SWITCH", "1")
    monkeypatch.setenv("EXCHANGE_LIVE_TRADING_ENABLED", "0")
    monkeypatch.setenv("TESTNET_EXECUTION_ENABLED", "0")
    monkeypatch.setenv("MARKET_STREAM_ENABLED", "1")

    app = FastAPI()
    database = FakeDatabase()
    app.state.project_database = database
    app.state.ai_organ_runtime_monitor = FakeMonitor()
    app.state.bybit_websocket_worker = FakeMarket()
    app.state.news_agent_network = FakeNews(database)
    app.state.global_auth_guard_installed = True
    return app


def test_health_center_reports_healthy_runtime(tmp_path: Path, monkeypatch) -> None:
    app = healthy_app(tmp_path, monkeypatch)
    snapshot = SystemHealthCenter(app).snapshot()
    assert snapshot["status"] == "healthy"
    assert snapshot["safe_mode"] is False
    assert snapshot["automatic_financial_recovery"] is False
    assert snapshot["automatic_failover"] is False
    assert snapshot["counts"] == {"healthy": 8, "degraded": 0, "blocked": 0}
    assert app.state.project_database.saved[("system_runtime", "health_center")]["status"] == "healthy"


def test_missing_kill_switch_blocks_system_even_with_other_components_healthy(
    tmp_path: Path, monkeypatch
) -> None:
    app = healthy_app(tmp_path, monkeypatch)
    monkeypatch.setenv("EXECUTION_KILL_SWITCH", "0")
    snapshot = SystemHealthCenter(app).snapshot()
    assert snapshot["status"] == "blocked"
    assert snapshot["safe_mode"] is True
    security = next(item for item in snapshot["components"] if item["component"] == "security")
    assert security["status"] == "blocked"
    assert any("kill switch" in blocker for blocker in security["blockers"])


def test_recovery_plan_is_advisory_and_never_financially_automatic(
    tmp_path: Path, monkeypatch
) -> None:
    app = healthy_app(tmp_path, monkeypatch)
    monkeypatch.setenv("BOT_TOKEN", "")
    install_system_health_api(app)
    client = TestClient(app)
    response = client.get("/api/system/recovery-plan")
    assert response.status_code == 200
    payload = response.json()
    assert payload["automatic_financial_recovery"] is False
    assert payload["automatic_failover"] is False
    assert payload["actions"]
    assert all(action["automatic"] is False for action in payload["actions"])


def test_installer_is_idempotent() -> None:
    app = FastAPI()
    install_system_health_api(app)
    first = app.state.system_health_center
    install_system_health_api(app)
    assert app.state.system_health_center is first
    paths = [route.path for route in app.routes]
    assert paths.count("/api/system/health") == 1
    assert paths.count("/api/system/recovery-plan") == 1


def test_non_finite_threshold_falls_back_safely(monkeypatch) -> None:
    monkeypatch.setenv("SYSTEM_DISK_WARNING_PERCENT", "nan")
    app = FastAPI()
    center = SystemHealthCenter(app)
    assert center.disk_warning_percent == 85.0
