"""Runtime truth fixes: F04 metrics cardinality, F16 auth status honesty, F17 Learning health."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard.canonical_runtime_compat_api import _runtime_truth
from dashboard.global_auth_guard import auth_disabled
from dashboard.release_status_api import release_status
from dashboard.system_health_api import SystemHealthCenter
from observability.metrics import _bounded_path, observe_http


def test_f16_release_status_reports_effective_auth_when_env_bypass_is_ignored(monkeypatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "1")
    monkeypatch.setenv("SHARIPOVAI_BUILD_SHA", "c" * 40)

    assert auth_disabled() is False
    report = release_status()

    assert report["disable_auth_env"] is True
    assert report["auth_enabled"] is True
    assert report["auth_enforced"] is True


def test_f16_security_status_does_not_claim_auth_disabled_in_production(monkeypatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("RENDER", "1")
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "1")
    monkeypatch.setenv("AUTH_SECRET", "test-secret")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "admin-password-123")
    monkeypatch.setenv("EXECUTION_KILL_SWITCH", "1")

    import dashboard

    app = dashboard.create_production_app()
    with TestClient(app, follow_redirects=False) as client:
        status = client.get("/api/security/status")
        protected = client.get("/api/system/release-truth")

    assert status.status_code == 200
    payload = status.json()
    assert payload["disable_auth_env"] is True
    assert payload["auth_enabled"] is True
    assert payload["auth_enforced"] is True
    assert protected.status_code == 401


def test_f17_aggregate_health_degrades_when_learning_organ_is_degraded(
    tmp_path: Path, monkeypatch
) -> None:
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
    monkeypatch.setattr(
        "dashboard.system_health_api.shutil.disk_usage",
        lambda _target: SimpleNamespace(total=100, used=40, free=60),
    )

    class Database:
        def health(self):
            return {"status": "ok", "backend": "sqlite"}

    class Market:
        def status(self):
            return {"verified": True, "database_backed": True, "worker_running": True}

    class News:
        def __init__(self, database):
            self.database = database
            self.agents = [object(), object()]

        def snapshot(self):
            return {"status": "running", "last_error": ""}

    class Monitor:
        def snapshot(self):
            return {
                "status": "degraded",
                "organ_count": 9,
                "monitor_running": True,
                "counts": {"healthy": 8, "degraded": 1, "blocked": 0},
                "organs": [
                    {
                        "organ_id": "learning_engine",
                        "status": "degraded",
                        "evidence": [],
                        "blockers": ["no persisted self-learning supervisor evidence"],
                    }
                ],
            }

    app = FastAPI()
    database = Database()
    app.state.project_database = database
    app.state.ai_organ_runtime_monitor = Monitor()
    app.state.bybit_websocket_worker = Market()
    app.state.news_agent_network = News(database)
    app.state.global_auth_guard_installed = True

    snapshot = SystemHealthCenter(app).snapshot()
    assert snapshot["status"] == "degraded"
    assert snapshot["counts"]["healthy"] < 9
    assert snapshot["counts"]["degraded"] >= 1
    learning = next(item for item in snapshot["components"] if item["component"] == "learning")
    assert learning["status"] == "degraded"
    ai_organs = next(item for item in snapshot["components"] if item["component"] == "ai_organs")
    assert ai_organs["status"] == "degraded"


def test_f17_runtime_truth_is_not_healthy_when_learning_is_degraded(monkeypatch) -> None:
    monkeypatch.setenv("EXECUTION_KILL_SWITCH", "1")
    monkeypatch.setenv("TESTNET_EXECUTION_ENABLED", "0")
    monkeypatch.setenv("EXCHANGE_LIVE_TRADING_ENABLED", "0")
    monkeypatch.setenv("FEATURE_BYBIT_LIVE_EXECUTION", "0")
    monkeypatch.setenv("AUTONOMOUS_TESTNET_ENABLED", "0")

    class Loop:
        def snapshot(self):
            return {
                "status": "ok",
                "worker_running": True,
                "database_backed": True,
                "equity": 100.0,
                "cash": 100.0,
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.0,
                "total_fees": 0.0,
                "positions": {},
                "trades": [],
                "trade_history_count": 0,
                "real_execution_enabled": False,
                "market_stream": {"verified": True},
            }

        def trade_history(self, limit=200):
            return []

        def event_history(self, limit=200):
            return []

    class Monitor:
        def snapshot(self):
            return {
                "status": "degraded",
                "organ_count": 9,
                "counts": {"healthy": 8, "degraded": 1, "blocked": 0},
                "organs": [
                    {
                        "organ_id": "learning_engine",
                        "status": "degraded",
                        "blockers": ["self-learning supervisor is enabled but not running"],
                        "evidence": [],
                    }
                ],
                "database_backed": True,
            }

    app = FastAPI()
    app.state.autonomous_paper_loop = Loop()
    app.state.ai_organ_runtime_monitor = Monitor()
    truth = _runtime_truth(app)
    assert truth["status"] == "degraded"
    assert truth["learning"]["status"] == "degraded"


def test_f04_http_path_labels_collapse_crypto_symbols_and_ids() -> None:
    assert _bounded_path("/api/market/quote/BTCUSDT") == "/api/market/quote/:id"
    assert _bounded_path("/api/market/candles/ethusdt") == "/api/market/candles/:id"
    assert _bounded_path("/api/users/42/profile") == "/api/users/:id/profile"
    assert (
        _bounded_path("/api/items/550e8400-e29b-41d4-a716-446655440000")
        == "/api/items/:id"
    )
    # Static routes remain intact.
    assert _bounded_path("/api/release/status") == "/api/release/status"

    observe_http(method="GET", path="/api/market/quote/SOLUSDT", status_code=200, duration_seconds=0.01)
    observe_http(method="GET", path="/api/market/quote/DOGEUSDT", status_code=200, duration_seconds=0.02)
