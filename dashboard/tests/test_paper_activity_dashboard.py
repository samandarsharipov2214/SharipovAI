from __future__ import annotations

from fastapi.testclient import TestClient

from dashboard.app import create_app


class DummyRunner:
    def run(self):
        raise RuntimeError("not used")


def test_paper_activity_api_installed_via_dashboard(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PAPER_ACTIVITY_STATE_FILE", str(tmp_path / "paper.json"))
    monkeypatch.setenv("VIRTUAL_ACCOUNT_STATE_FILE", str(tmp_path / "virtual.json"))
    monkeypatch.setenv("PAPER_ACTIVITY_AUTORUN_ENABLED", "0")
    monkeypatch.setenv("VIRTUAL_ACCOUNT_BOOTSTRAP_TICKS", "0")
    client = TestClient(create_app(runner_factory=DummyRunner))

    state_response = client.get("/api/paper-activity/state")
    assert state_response.status_code == 200
    state = state_response.json()["state"]
    assert state["summary"]["trade_count"] == 0
    assert state["summary"]["trade_count"] == len(state.get("trades", []))
    assert state_response.json()["autorun"]["enabled"] is False

    tick = client.post("/api/paper-activity/tick", json={"force": True})
    assert tick.status_code == 200
    assert tick.json()["status"] in {"ok", "wait", "blocked"}

    current = client.get("/api/paper-activity/state").json()["state"]
    assert current["summary"]["trade_count"] == len(current.get("trades", []))
    assert all(trade.get("real_order_placed") is not True for trade in current.get("trades", []))

    trades = client.get("/api/paper-activity/trades")
    assert trades.status_code == 200
    assert trades.json()["summary"]["trade_count"] == len(trades.json()["trades"])

    page = client.get("/paper-activity")
    assert page.status_code == 200
    assert "Paper Activity Engine" in page.text
    assert "Все сделки" in page.text
    assert "JSON all trades" in page.text
    assert "Autorun" in page.text


def test_paper_activity_catch_up_endpoint(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PAPER_ACTIVITY_STATE_FILE", str(tmp_path / "paper.json"))
    monkeypatch.setenv("VIRTUAL_ACCOUNT_STATE_FILE", str(tmp_path / "virtual.json"))
    monkeypatch.setenv("PAPER_ACTIVITY_AUTORUN_ENABLED", "0")
    client = TestClient(create_app(runner_factory=DummyRunner))

    response = client.post("/api/paper-activity/catch-up", json={"max_ticks": 3})

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["catch_up_ticks"] >= 0


def test_launch_check_contains_paper_activity(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PAPER_ACTIVITY_STATE_FILE", str(tmp_path / "paper.json"))
    monkeypatch.setenv("VIRTUAL_ACCOUNT_STATE_FILE", str(tmp_path / "virtual.json"))
    monkeypatch.setenv("PAPER_ACTIVITY_AUTORUN_ENABLED", "0")
    client = TestClient(create_app(runner_factory=DummyRunner))

    response = client.get("/api/launch-check")

    assert response.status_code == 200
    check_names = {item["name"] for item in response.json()["checks"]}
    assert "Paper Activity" in check_names
    assert response.json()["important_urls"]["paper_activity"] == "/paper-activity"
