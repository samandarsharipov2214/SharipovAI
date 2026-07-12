from fastapi import FastAPI

from dashboard.full_system_audit_api import REQUIRED_ROUTES, build_audit, install_full_system_audit_api


def test_audit_is_read_only_and_covers_ten_areas():
    app = FastAPI()
    for routes in REQUIRED_ROUTES.values():
        for path in routes:
            app.add_api_route(path, lambda: {"status": "ok"}, methods=["GET"])
    app.state.project_database = object()
    app.state.bybit_websocket_worker = object()
    app.state.news_agent_network = object()
    app.state.ai_organ_runtime_monitor = object()
    app.state.system_health_center = object()

    report = build_audit(app)

    assert report["read_only"] is True
    assert report["orders_sent"] is False
    assert report["automatic_recovery"] is False
    assert report["summary"]["total"] >= 10
    assert {item["name"] for item in report["checks"]} >= {
        "api", "ai", "integration", "realtime", "paper_execution",
        "decisions", "errors", "vps", "runtime_objects", "safe_trading",
        "dead_code_and_duplicates",
    }


def test_missing_routes_are_reported_not_hidden():
    report = build_audit(FastAPI())
    assert report["status"] == "attention_required"
    assert report["summary"]["failed"] > 0
    assert any(item["blockers"] for item in report["checks"])


def test_installer_is_idempotent_and_get_only():
    app = FastAPI()
    install_full_system_audit_api(app)
    install_full_system_audit_api(app)
    routes = [route for route in app.routes if getattr(route, "path", "") == "/api/system/full-audit"]
    assert len(routes) == 1
    assert routes[0].methods == {"GET"}
