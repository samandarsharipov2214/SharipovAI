from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard.auth import AdminPrincipal, admin_principal
from dashboard.routers.leadership import router
from experiments import ExperimentRegistry
from storage import ProjectDatabase


def _completed(registry: ExperimentRegistry, experiment_id: str, pnl: float) -> None:
    created = registry.create(
        experiment_id=experiment_id,
        commit_sha="abcdef1",
        manifest={"manifest_id": "btc-1m", "version": "1", "validated": True},
        strategy_name=experiment_id,
        strategy_config={},
        backtest_config={},
    )
    running = registry.record_result(
        experiment_id,
        "walk_forward",
        {
            "net_pnl": pnl,
            "return_percent": pnl,
            "max_drawdown_percent": 2.0,
            "profitable_window_percent": 70.0,
        },
        actor="test",
        expected_version=created["version"],
    )
    registry.complete(
        experiment_id,
        actor="test",
        expected_version=running["version"],
    )


def test_leadership_dashboard_registers_challenger_without_execution_side_effects(tmp_path) -> None:
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'project.db'}")
    registry = ExperimentRegistry(database)
    _completed(registry, "exp-a", 10.0)
    _completed(registry, "exp-b", 5.0)

    app = FastAPI()
    app.state.project_database = database
    app.include_router(router)
    app.dependency_overrides[admin_principal] = lambda: AdminPrincipal("tester")
    client = TestClient(app)

    registered = client.post(
        "/api/strategy-leadership/spot:testnet/challengers",
        json={
            "experiment_id": "exp-a",
            "reason": "candidate passed completed research review",
            "expected_version": 0,
        },
    )
    assert registered.status_code == 200
    body = registered.json()
    assert body["runtime_deployment_changed"] is False
    assert body["leadership"]["challengers"]["exp-a"]["status"] == "active"

    page = client.get("/champion-challenger?scope=spot:testnet")
    assert page.status_code == 200
    assert "Champion / Challenger" in page.text
    assert "exp-a" in page.text
    assert "cannot deploy code" in page.text

    snapshot = client.get("/api/strategy-leadership/spot:testnet")
    assert snapshot.status_code == 200
    assert snapshot.json()["runtime_deployment_changed"] is False
    assert snapshot.json()["leadership"]["champion_experiment_id"] == ""
