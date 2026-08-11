"""Tests for persistent demo account API."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dashboard import create_app


@pytest.fixture(autouse=True)
def _public_dashboard_test_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "1")


def test_demo_state_never_fabricates_a_funded_account(monkeypatch, tmp_path: Path) -> None:
    """A compatibility endpoint reports missing canonical runtime honestly."""

    monkeypatch.setenv("DEMO_STATE_FILE", str(tmp_path / "demo_state.json"))
    client = TestClient(create_app())

    response = client.get("/api/demo/state")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "unavailable"
    assert payload["source_of_truth"] == "CouncilAuthorizedPaperLoop"
    assert payload["state"]["equity"] is None
    assert payload["state"]["cash"] is None


def test_demo_balance_cannot_create_a_second_paper_account(monkeypatch, tmp_path: Path) -> None:
    """Legacy balances cannot diverge from the Council-owned runtime."""

    monkeypatch.setenv("DEMO_STATE_FILE", str(tmp_path / "demo_state.json"))
    client = TestClient(create_app())

    response = client.post("/api/demo/balance", json={"balance": 20000})

    assert response.status_code == 410
    payload = response.json()
    assert payload["source_of_truth"] == "CouncilAuthorizedPaperLoop"
    assert payload["automatic_legacy_mutation"] is False


def test_demo_chat_cannot_execute_or_answer_from_legacy_state(monkeypatch, tmp_path: Path) -> None:
    """The old command sandbox is retired instead of becoming a second engine."""

    monkeypatch.setenv("DEMO_STATE_FILE", str(tmp_path / "demo_state.json"))
    monkeypatch.setenv("EXCHANGE_MODE", "sandbox")
    client = TestClient(create_app())

    response = client.post("/api/demo/chat", json={"message": "найди выгодные условия Bybit"})

    assert response.status_code == 410
    payload = response.json()
    assert payload["status"] == "deprecated_operation_blocked"
    assert payload["automatic_legacy_mutation"] is False


def test_demo_chat_is_blocked_before_legacy_engine_can_fail(monkeypatch) -> None:
    """The retired engine is never invoked through the public compatibility URL."""

    import dashboard.demo_api as demo_api

    def broken_run_ai_command(_message: str) -> dict[str, object]:
        raise RuntimeError("boom")

    monkeypatch.setattr(demo_api, "run_ai_command", broken_run_ai_command)
    client = TestClient(create_app())

    response = client.post("/api/demo/chat", json={"message": "найди выгодные условия Bybit"})

    assert response.status_code == 410
    payload = response.json()
    assert payload["status"] == "deprecated_operation_blocked"


def test_demo_chat_cannot_buy_outside_council_pipeline(monkeypatch, tmp_path: Path) -> None:
    """A chat request cannot bypass Council, Risk and Decision Quality."""

    monkeypatch.setenv("DEMO_STATE_FILE", str(tmp_path / "demo_state.json"))
    monkeypatch.setenv("EXCHANGE_MODE", "sandbox")
    monkeypatch.setenv("EXCHANGE_DEFAULT_FEE_RATE", "0.001")
    client = TestClient(create_app())

    response = client.post("/api/demo/chat", json={"message": "купи BTC виртуально"})

    assert response.status_code == 410
    payload = response.json()
    assert payload["status"] == "deprecated_operation_blocked"


def test_demo_chat_cannot_settle_outside_canonical_runtime(monkeypatch, tmp_path: Path) -> None:
    """A legacy sell cannot create a settlement detached from a decision ID."""

    monkeypatch.setenv("DEMO_STATE_FILE", str(tmp_path / "demo_state.json"))
    monkeypatch.setenv("EXCHANGE_MODE", "sandbox")
    monkeypatch.setenv("EXCHANGE_DEFAULT_FEE_RATE", "0.001")
    client = TestClient(create_app())

    response = client.post("/api/demo/chat", json={"message": "продай BTC"})

    assert response.status_code == 410
    payload = response.json()
    assert payload["status"] == "deprecated_operation_blocked"


def test_demo_chat_cannot_claim_legacy_monitoring_is_online(monkeypatch, tmp_path: Path) -> None:
    """A compatibility surface must not manufacture a connected exchange status."""

    monkeypatch.setenv("DEMO_STATE_FILE", str(tmp_path / "demo_state.json"))
    monkeypatch.setenv("EXCHANGE_MODE", "sandbox")
    client = TestClient(create_app())

    response = client.post("/api/demo/chat", json={"message": "мониторинг онлайн биржи"})

    assert response.status_code == 410
    payload = response.json()
    assert payload["status"] == "deprecated_operation_blocked"
