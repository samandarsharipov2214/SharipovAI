from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard.auth import AdminPrincipal, admin_principal
from dashboard.routers import execution_status as execution_status_module
from dashboard.routers.execution_status import router


class FakeExecutionClient:
    def status(self):
        return {
            "mode": "sandbox",
            "testnet_execution_enabled": False,
            "live_execution_enabled": False,
            "kill_switch": True,
            "mainnet_hard_blocked": True,
        }


class FakeAssessment:
    def to_dict(self):
        return {"status": "blocked", "stage": 2}


class FakeStageController:
    def assess(self):
        return FakeAssessment()


class FakeJournal:
    def summary(self):
        return {"status": "ok", "record_count": 7, "database_backed": True}


class FakePaperEngine:
    def state(self, *, catch_up: bool = False):
        assert catch_up is False
        return {
            "status": "ok",
            "summary": {
                "equity": 10_000.0,
                "cash": 8_000.0,
                "net_pnl": 125.0,
                "deployed_notional": 2_000.0,
                "reserve_amount": 2_000.0,
                "open_positions": 1,
            },
        }


def _app(monkeypatch) -> FastAPI:
    monkeypatch.setattr(
        execution_status_module,
        "PaperActivityEngine",
        FakePaperEngine,
    )
    app = FastAPI()
    app.state.execution_client = FakeExecutionClient()
    app.state.stage_controller = FakeStageController()
    app.state.execution_journal = FakeJournal()
    app.include_router(router)
    app.dependency_overrides[admin_principal] = lambda: AdminPrincipal("admin")
    return app


def test_execution_status_api_uses_real_runtime_shapes(monkeypatch) -> None:
    with TestClient(_app(monkeypatch)) as client:
        response = client.get("/api/execution/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["execution_blocked"] is True
    assert payload["canonical_write_path"] == "ApprovedExecutionRequest"
    assert payload["raw_order_api"] == "removed"
    assert payload["mainnet_available"] is False
    assert payload["risk"]["equity"] == 10_000.0
    assert payload["risk"]["exposure_percent"] == 20.0
    assert payload["risk"]["net_pnl"] == 125.0


def test_execution_status_page_renders_operational_metrics(monkeypatch) -> None:
    with TestClient(_app(monkeypatch)) as client:
        response = client.get("/execution-status")

    assert response.status_code == 200
    assert "Execution Status" in response.text
    assert "ApprovedExecutionRequest" in response.text
    assert "Paper net PnL" in response.text
