from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI

from dashboard.news_agent_network_api import _bridge_status, _status
from storage import ProjectDatabase


class _Network:
    def __init__(self, database: ProjectDatabase, agents: list[dict]) -> None:
        self.database = database
        self._agents = agents

    def snapshot(self):
        return {
            "status": "running",
            "last_error": "",
            "agents": self._agents,
            "hub": {},
        }


def test_news_status_degrades_when_any_source_agent_is_not_active(tmp_path) -> None:
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'project.db'}")
    database.initialize()
    network = _Network(
        database,
        [
            {"source_id": "active_source", "status": "active"},
            {"source_id": "stale_source", "status": "stale"},
        ],
    )

    result = _status(network, database)

    assert result["status"] == "warning"
    assert result["healthy_agent_count"] == 1
    assert result["degraded_agent_count"] == 1
    assert result["degraded_agents"] == ["stale_source"]


def test_shared_database_consumer_active_requires_all_canonical_consumers(tmp_path) -> None:
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'project.db'}")
    database.initialize()
    app = FastAPI()
    app.state.project_database = database
    app.state.autonomous_council_provider = SimpleNamespace(risk_service=object())
    app.state.canonical_paper_decision_runtime = object()
    app.state.autonomous_paper_loop = object()
    app.state.self_learning_supervisor = object()

    healthy = _bridge_status(database, app=app)
    del app.state.self_learning_supervisor
    degraded = _bridge_status(database, app=app)

    assert healthy["status"] == "ok"
    assert healthy["consumer_active"] is True
    assert all(healthy["consumer_components"].values())
    assert degraded["status"] == "warning"
    assert degraded["consumer_active"] is False
    assert degraded["consumer_components"]["learning_engine"] is False
    assert healthy["sent_count"] is None
