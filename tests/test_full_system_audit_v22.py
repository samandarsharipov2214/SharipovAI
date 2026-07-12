from __future__ import annotations

from fastapi import FastAPI

from dashboard.full_system_audit_api import REQUIRED_ROUTES, build_audit, install_full_system_audit_api


class Database:
    def health(self):
        return {"status": "ok", "backend": "sqlite"}

    def put_json(self, *_args, **_kwargs):
        return None


class Worker:
    def status(self):
        return {
            "enabled": True,
            "worker_running": True,
            "verified": True,
            "database_backed": True,
            "synthetic_fallback_used": False,
        }


class NewsNetwork:
    def snapshot(self):
        return {"status": "running", "database_backed": True, "last_error": ""}


class OrganMonitor:
    def snapshot(self):
        return {"status": "healthy", "organ_count": 9, "monitor_running": True}


class HealthCenter:
    def snapshot(self):
        return {"status": "healthy", "safe_mode": False}


def _healthy_app(monkeypatch) -> FastAPI:
    monkeypatch.setenv("EXECUTION_KILL_SWITCH", "1")
    for name in (
        "EXCHANGE_LIVE_TRADING_ENABLED",
        "TESTNET_EXECUTION_ENABLED",
        "AUTONOMOUS_TESTNET_ENABLED",
        "AUTONOMOUS_TESTNET_BRIDGE_ENABLED",
    ):
        monkeypatch.setenv(name, "0")

    app = FastAPI()
    for path in sorted({path for routes in REQUIRED_ROUTES.values() for path in routes}):
        app.add_api_route(path, lambda: {"status": "ok"}, methods=["GET"])
    app.state.project_database = Database()
    app.state.bybit_websocket_worker = Worker()
    app.state.news_agent_network = NewsNetwork()
    app.state.ai_organ_runtime_monitor = OrganMonitor()
    app.state.system_health_center = HealthCenter()
    return app


def test_audit_is_read_only_and_covers_ten_areas(monkeypatch):
    report = build_audit(_healthy_app(monkeypatch))

    assert report["status"] == "passed"
    assert report["read_only"] is True
    assert report["orders_sent"] is False
    assert report["automatic_recovery"] is False
    assert report["summary"]["total"] >= 10
    assert {item["name"] for item in report["checks"]} >= {
        "api",
        "ai",
        "integration",
        "realtime",
        "paper_execution",
        "decisions",
        "errors",
        "vps",
        "runtime_objects",
        "database_runtime",
        "market_realtime_runtime",
        "news_realtime_runtime",
        "ai_organs_runtime",
        "vps_runtime_health",
        "safe_trading",
        "dead_code_and_duplicates",
    }


def test_missing_routes_are_reported_not_hidden(monkeypatch):
    monkeypatch.setenv("EXECUTION_KILL_SWITCH", "1")
    report = build_audit(FastAPI())
    assert report["status"] == "attention_required"
    assert report["summary"]["failed"] > 0
    assert any(item["blockers"] for item in report["checks"])


def test_same_path_with_different_methods_is_not_a_duplicate(monkeypatch):
    app = _healthy_app(monkeypatch)
    app.add_api_route("/api/crash-test", lambda: {"status": "ok"}, methods=["GET"])
    app.add_api_route("/api/crash-test", lambda: {"status": "ok"}, methods=["POST"])

    report = build_audit(app)
    duplicate_check = next(item for item in report["checks"] if item["name"] == "dead_code_and_duplicates")
    assert duplicate_check["status"] == "passed"


def test_same_method_and_path_collision_is_reported(monkeypatch):
    app = _healthy_app(monkeypatch)
    app.add_api_route("/api/collision", lambda: {"status": "ok"}, methods=["GET"])
    app.add_api_route("/api/collision", lambda: {"status": "ok"}, methods=["GET"])

    report = build_audit(app)
    duplicate_check = next(item for item in report["checks"] if item["name"] == "dead_code_and_duplicates")
    assert duplicate_check["status"] == "failed"
    assert "duplicate_route=GET /api/collision" in duplicate_check["blockers"]


def test_disabled_kill_switch_and_testnet_bridge_fail_closed(monkeypatch):
    app = _healthy_app(monkeypatch)
    monkeypatch.setenv("EXECUTION_KILL_SWITCH", "0")
    monkeypatch.setenv("AUTONOMOUS_TESTNET_ENABLED", "1")
    monkeypatch.setenv("AUTONOMOUS_TESTNET_BRIDGE_ENABLED", "1")

    report = build_audit(app)
    safety = next(item for item in report["checks"] if item["name"] == "safe_trading")
    assert safety["status"] == "failed"
    assert "execution_kill_switch_disabled" in safety["blockers"]
    assert "unsafe_flag_enabled=AUTONOMOUS_TESTNET_ENABLED" in safety["blockers"]


def test_route_presence_cannot_hide_disabled_market_runtime(monkeypatch):
    app = _healthy_app(monkeypatch)

    class DisabledWorker:
        def status(self):
            return {
                "enabled": False,
                "worker_running": False,
                "verified": False,
                "database_backed": True,
                "synthetic_fallback_used": False,
            }

    app.state.bybit_websocket_worker = DisabledWorker()
    report = build_audit(app)
    market = next(item for item in report["checks"] if item["name"] == "market_realtime_runtime")
    assert market["status"] == "failed"


def test_installer_is_idempotent_and_get_only():
    app = FastAPI()
    install_full_system_audit_api(app)
    install_full_system_audit_api(app)
    routes = [route for route in app.routes if getattr(route, "path", "") == "/api/system/full-audit"]
    assert len(routes) == 1
    assert routes[0].methods == {"GET"}
