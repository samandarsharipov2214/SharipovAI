from __future__ import annotations

from fastapi.testclient import TestClient

from dashboard.app import create_app


class DummyRunner:
    def run(self):
        raise RuntimeError("not used")


def test_paper_activity_api_installed_via_dashboard(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PAPER_ACTIVITY_STATE_FILE", str(tmp_path / "paper.json"))
    client = TestClient(create_app(runner_factory=DummyRunner))

    state = client.get("/api/paper-activity/state")
    assert state.status_code == 200
    assert state.json()["summary"]["trade_count"] == 0

    tick = client.post("/api/paper-activity/tick", json={"force": True})
    assert tick.status_code == 200
    assert tick.json()["state"]["summary"]["trade_count"] == 1

    page = client.get("/paper-activity")
    assert page.status_code == 200
    assert "Paper Activity Engine" in page.text


def test_launch_check_contains_paper_activity(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PAPER_ACTIVITY_STATE_FILE", str(tmp_path / "paper.json"))
    client = TestClient(create_app(runner_factory=DummyRunner))

    response = client.get("/api/launch-check")

    assert response.status_code == 200
    check_names = {item["name"] for item in response.json()["checks"]}
    assert "Paper Activity" in check_names
    assert response.json()["important_urls"]["paper_activity"] == "/paper-activity"
