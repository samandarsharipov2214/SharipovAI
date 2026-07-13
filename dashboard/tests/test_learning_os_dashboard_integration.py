from __future__ import annotations

from fastapi.testclient import TestClient

from dashboard.app import create_app
from learning.ai_learning_core import BOT_NAMES


class DummyRunner:
    def run(self):
        raise RuntimeError("not used")


def test_learning_os_endpoints_installed_in_dashboard(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LEARNING_MEMORY_DB", str(tmp_path / "learning.sqlite3"))
    client = TestClient(create_app(runner_factory=DummyRunner))

    close_response = client.post("/api/learning-os/close-gap")
    assert close_response.status_code == 200
    assert close_response.json()["status"] == "ok"

    snapshot_response = client.get("/api/learning-os/snapshot")
    assert snapshot_response.status_code == 200
    assert snapshot_response.json()["summary"]["bot_count"] == len(BOT_NAMES)

    page_response = client.get("/learning-os")
    assert page_response.status_code == 200
    assert 'id="content"' in page_response.text
    assert 'data-page="learning"' in page_response.text
    assert "learning_evidence_reports_v17.js" in page_response.text


def test_home_exposes_learning_navigation() -> None:
    response = TestClient(create_app(runner_factory=DummyRunner)).get("/")
    assert response.status_code == 200
    assert 'data-page="learning"' in response.text
    assert "Центр обучения" in response.text
