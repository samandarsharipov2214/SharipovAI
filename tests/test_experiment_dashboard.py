from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard.auth import AdminPrincipal, admin_principal
from dashboard.routers.experiments import router
from experiments import ExperimentRegistry
from storage import ProjectDatabase


def _create(registry: ExperimentRegistry, experiment_id: str, pnl: float) -> None:
    created = registry.create(
        experiment_id=experiment_id,
        commit_sha="9d4ec8a",
        manifest={
            "manifest_id": "btc-1m",
            "version": "1",
            "validated": True,
        },
        strategy_name=experiment_id,
        strategy_config={},
        backtest_config={},
    )
    running = registry.record_result(
        experiment_id,
        "walk_forward",
        {
            "net_pnl": pnl,
            "return_percent": pnl / 100.0,
            "max_drawdown_percent": 2.0,
            "profitable_window_percent": 66.0,
        },
        actor="test",
        expected_version=created["version"],
    )
    registry.complete(
        experiment_id,
        actor="test",
        expected_version=running["version"],
    )


def test_experiment_dashboard_is_read_only_and_compares_results(tmp_path) -> None:
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'project.db'}")
    registry = ExperimentRegistry(database)
    _create(registry, "exp-a", 100.0)
    _create(registry, "exp-b", 50.0)

    app = FastAPI()
    app.state.project_database = database
    app.include_router(router)
    app.dependency_overrides[admin_principal] = lambda: AdminPrincipal("tester")
    client = TestClient(app)

    listed = client.get("/api/experiments")
    assert listed.status_code == 200
    assert listed.json()["count"] == 2

    compared = client.get("/api/experiments/compare?ids=exp-a,exp-b")
    assert compared.status_code == 200
    assert compared.json()["ranking"] == ["exp-a", "exp-b"]

    page = client.get("/backtest-results")
    assert page.status_code == 200
    assert "Backtest Results" in page.text
    assert "exp-a" in page.text
    assert "ApprovedExecutionRequest" not in page.text

    comparison_page = client.get("/experiment-comparison?ids=exp-a,exp-b")
    assert comparison_page.status_code == 200
    assert "Experiment Comparison" in comparison_page.text
