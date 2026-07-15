from __future__ import annotations

from fastapi.testclient import TestClient

from dashboard import create_app


class DummyRunner:
    def run(self):
        raise RuntimeError("not used")


def test_paper_activity_api_is_installed_and_truthful_without_market_evidence(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PAPER_ACTIVITY_STATE_FILE", str(tmp_path / "paper.json"))
    monkeypatch.setenv("PAPER_ACTIVITY_AUTORUN_ENABLED", "0")
    monkeypatch.setenv("PAPER_ACTIVITY_BOOTSTRAP_TICKS", "0")
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "1")
    client = TestClient(create_app(runner_factory=DummyRunner))

    state = client.get("/api/paper-activity/state")
    assert state.status_code == 200
    assert state.json()["state"]["summary"]["trade_count"] == 0
    assert state.json()["state"]["real_orders_blocked"] is True
    assert state.json()["autorun"]["enabled"] is False

    tick = client.post("/api/paper-activity/tick", json={"force": True})
    assert tick.status_code == 200
    assert tick.json()["result"]["status"] == "blocked"
    assert tick.json()["state"]["summary"]["trade_count"] == 0
    assert tick.json()["state"]["summary"]["skipped_count"] >= 1

    trades = client.get("/api/paper-activity/trades")
    assert trades.status_code == 200
    assert trades.json()["summary"]["trade_count"] == len(trades.json()["trades"]) == 0

    page = client.get("/paper-activity")
    assert page.status_code == 200
    assert "Paper Activity Engine" in page.text
    assert "Все сделки" in page.text
    assert "JSON all trades" in page.text
    assert "Autorun" in page.text


def test_paper_activity_catch_up_never_fabricates_market_evidence(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PAPER_ACTIVITY_STATE_FILE", str(tmp_path / "paper.json"))
    monkeypatch.setenv("PAPER_ACTIVITY_AUTORUN_ENABLED", "0")
    monkeypatch.setenv("PAPER_ACTIVITY_BOOTSTRAP_TICKS", "0")
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "1")
    client = TestClient(create_app(runner_factory=DummyRunner))

    response = client.post("/api/paper-activity/catch-up", json={"max_ticks": 3})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["catch_up_ticks"] >= 1
    assert payload["state"]["summary"]["trade_count"] == 0
    assert payload["state"]["summary"]["skipped_count"] >= 1


def test_launch_check_contains_paper_activity(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PAPER_ACTIVITY_STATE_FILE", str(tmp_path / "paper.json"))
    monkeypatch.setenv("PAPER_ACTIVITY_AUTORUN_ENABLED", "0")
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "1")
    client = TestClient(create_app(runner_factory=DummyRunner))

    response = client.get("/api/launch-check")

    assert response.status_code == 200
    check_names = {item["name"] for item in response.json()["checks"]}
    assert "Paper Activity" in check_names
    assert response.json()["important_urls"]["paper_activity"] == "/paper-activity"
