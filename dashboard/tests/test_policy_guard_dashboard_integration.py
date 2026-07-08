from __future__ import annotations

from fastapi.testclient import TestClient

from dashboard.app import create_app
from learning.policy_journal import PolicyJournal


class DummyRun:
    decision = "WATCH"
    confidence = 70.0
    risk_level = "LOW"
    portfolio_value = 10000.0
    paper_cash = 9500.0
    paper_equity = 10000.0
    report = "ok"
    reason = "test"
    consensus = "MODERATE"
    consensus_agreement = 70.0
    paper_pnl = 0.0
    open_positions = 0


class DummyRunner:
    calls = 0

    def run(self) -> DummyRun:
        DummyRunner.calls += 1
        return DummyRun()


def _write_advice(path, recommended_action: str) -> None:
    PolicyJournal(path).add([], {"recommended_action": recommended_action, "must_notify_owner": recommended_action in {"block_action", "manual_review"}})


def test_policy_guard_blocks_api_run_before_runner_executes(tmp_path, monkeypatch) -> None:
    policy_file = tmp_path / "policy.json"
    monkeypatch.setenv("POLICY_JOURNAL_FILE", str(policy_file))
    _write_advice(policy_file, "block_action")
    DummyRunner.calls = 0
    client = TestClient(create_app(runner_factory=DummyRunner))

    response = client.get("/api/run")

    assert response.status_code == 403
    assert response.json()["error"] == "policy_guard_blocked"
    assert response.json()["decision"] == "block"
    assert DummyRunner.calls == 0


def test_policy_guard_blocks_trade_gate(tmp_path, monkeypatch) -> None:
    policy_file = tmp_path / "policy.json"
    monkeypatch.setenv("POLICY_JOURNAL_FILE", str(policy_file))
    _write_advice(policy_file, "block_action")
    client = TestClient(create_app(runner_factory=DummyRunner))

    response = client.post("/api/trade-gate", json={"symbol": "BTC/USDT"})

    assert response.status_code == 403
    assert response.json()["action_type"] == "trade"
    assert response.json()["recommended_action"] == "block_action"


def test_policy_guard_does_not_block_health_endpoint(tmp_path, monkeypatch) -> None:
    policy_file = tmp_path / "policy.json"
    monkeypatch.setenv("POLICY_JOURNAL_FILE", str(policy_file))
    _write_advice(policy_file, "block_action")
    client = TestClient(create_app(runner_factory=DummyRunner))

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_policy_guard_allows_api_run_without_block_action(tmp_path, monkeypatch) -> None:
    policy_file = tmp_path / "policy.json"
    monkeypatch.setenv("POLICY_JOURNAL_FILE", str(policy_file))
    _write_advice(policy_file, "continue")
    DummyRunner.calls = 0
    client = TestClient(create_app(runner_factory=DummyRunner))

    response = client.get("/api/run")

    assert response.status_code == 200
    assert response.json()["decision"] == "WATCH"
    assert DummyRunner.calls == 1
