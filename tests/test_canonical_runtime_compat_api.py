from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard.canonical_runtime_compat_api import install_canonical_runtime_compat_api


class _CanonicalLoop:
    def __init__(self) -> None:
        self.tick_count = 0

    def snapshot(self) -> dict[str, object]:
        return {
            "status": "ok",
            "source_of_truth": "autonomous_paper",
            "database_backed": True,
            "worker_running": True,
            "real_execution_enabled": False,
            "mutation_on_read": False,
            "wait_event_min_interval_seconds": 300.0,
            "cash": 9_500.0,
            "equity": 10_050.0,
            "realized_pnl": 40.0,
            "unrealized_pnl": 10.0,
            "total_fees": 2.0,
            "positions": {"BTCUSDT": {"quantity": 0.01, "entry_price": 50_000.0}},
            "market_stream": {"status": "running", "verified": True},
        }

    def trade_history(self, *, limit: int | None = None) -> list[dict[str, object]]:
        del limit
        return [{"id": "paper-1", "symbol": "BTCUSDT", "status": "CLOSED"}]

    def event_history(self, *, limit: int | None = None) -> list[dict[str, object]]:
        del limit
        return [{"event_id": "wait-1", "action": "WAIT"}]

    def tick(self) -> None:
        self.tick_count += 1


def _app() -> tuple[FastAPI, _CanonicalLoop, dict[str, bool]]:
    app = FastAPI()
    loop = _CanonicalLoop()
    app.state.autonomous_paper_loop = loop
    startup = {"legacy_started": False}

    @app.on_event("startup")
    def paper_activity_startup() -> None:
        startup["legacy_started"] = True

    @app.get("/api/virtual-account/state")
    def legacy_state() -> dict[str, str]:
        return {"status": "legacy"}

    @app.post("/api/paper-activity/reset")
    def legacy_reset() -> dict[str, str]:
        return {"status": "unsafe_legacy_reset"}

    install_canonical_runtime_compat_api(app)
    return app, loop, startup


def test_legacy_state_is_read_only_view_of_canonical_loop() -> None:
    app, _loop, startup = _app()

    with TestClient(app) as client:
        response = client.get("/api/virtual-account/state")

    assert startup["legacy_started"] is False
    assert response.status_code == 200
    assert response.headers["deprecation"] == "true"
    payload = response.json()
    assert payload["source_of_truth"] == "CouncilAuthorizedPaperLoop"
    assert payload["replacement"] == "/api/autonomous-paper/status"
    assert payload["state"]["mutation_on_read"] is False
    assert payload["state"]["summary"]["real_orders_blocked"] is True
    assert payload["state"]["summary"]["trade_count"] == 1


def test_demo_state_is_intercepted_by_canonical_adapter() -> None:
    app, _loop, _startup = _app()

    with TestClient(app) as client:
        response = client.get("/api/demo/state")

    assert response.status_code == 200
    assert response.json()["state"]["source_of_truth"] == "CouncilAuthorizedPaperLoop"
    assert response.json()["state"]["legacy_virtual_account_deprecated"] is True


def test_legacy_tick_is_blocked_instead_of_creating_second_execution_path() -> None:
    app, loop, _startup = _app()

    with TestClient(app) as client:
        response = client.post("/api/virtual-account/tick")

    assert response.status_code == 410
    assert loop.tick_count == 0
    assert response.json()["source_of_truth"] == "CouncilAuthorizedPaperLoop"
    assert response.json()["replacement"] == "/api/autonomous-paper/tick"
    assert response.json()["automatic_legacy_mutation"] is False


def test_legacy_reset_and_catch_up_are_gone() -> None:
    app, _loop, _startup = _app()

    with TestClient(app) as client:
        reset = client.post("/api/paper-activity/reset")
        catch_up = client.post("/api/virtual-account/catch-up")

    assert reset.status_code == 410
    assert catch_up.status_code == 410
    assert reset.json()["automatic_legacy_mutation"] is False
    assert catch_up.json()["automatic_legacy_mutation"] is False


def test_runtime_truth_reports_canonical_owners_and_locked_execution(monkeypatch) -> None:
    monkeypatch.setenv("EXECUTION_KILL_SWITCH", "1")
    monkeypatch.setenv("TESTNET_EXECUTION_ENABLED", "0")
    monkeypatch.setenv("EXCHANGE_LIVE_TRADING_ENABLED", "0")
    app, _loop, _startup = _app()

    with TestClient(app) as client:
        response = client.get("/api/system/runtime-truth")

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_of_truth"]["paper"] == "CouncilAuthorizedPaperLoop"
    assert payload["source_of_truth"]["risk"] == "risk_engine.canonical_service"
    assert payload["safety"]["status"] == "locked"
    assert payload["legacy"]["api_run_allowed_for_ui"] is False
    assert payload["legacy"]["paper_activity_engine_active"] is False
