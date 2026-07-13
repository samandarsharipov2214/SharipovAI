"""Tests for the deprecated read-only Demo compatibility API."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from dashboard import create_app


def _configure_virtual_state(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("VIRTUAL_ACCOUNT_STATE_FILE", str(tmp_path / "virtual.json"))
    monkeypatch.setenv("VIRTUAL_ACCOUNT_BOOTSTRAP_TICKS", "0")
    monkeypatch.setenv("VIRTUAL_ACCOUNT_MAX_CATCH_UP_TICKS", "0")


def test_demo_state_is_deprecated_virtual_account_mirror(monkeypatch, tmp_path: Path) -> None:
    _configure_virtual_state(monkeypatch, tmp_path)
    client = TestClient(create_app())
    response = client.get("/api/demo/state")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["deprecated"] is True
    assert payload["use"] == "/api/virtual-account/state"
    assert payload["state"]["mode"] == "VIRTUAL_ACCOUNT"
    assert payload["state"]["synthetic_prices_used"] is False
    assert payload["state"]["legacy_execution_enabled"] is False
    assert payload["state"]["online_monitoring"]["real_orders_blocked"] is True


def test_demo_balance_mutation_is_blocked(monkeypatch, tmp_path: Path) -> None:
    _configure_virtual_state(monkeypatch, tmp_path)
    response = TestClient(create_app()).post("/api/demo/balance", json={"balance": 20000})
    assert response.status_code == 409
    payload = response.json()
    assert payload["status"] == "blocked"
    assert payload["real_orders_blocked"] is True


def test_demo_chat_remains_informational(monkeypatch, tmp_path: Path) -> None:
    _configure_virtual_state(monkeypatch, tmp_path)
    response = TestClient(create_app()).post("/api/demo/chat", json={"message": "какой статус системы"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["deprecated"] is True
    assert payload["state"]["legacy_execution_enabled"] is False


def test_demo_chat_returns_json_when_engine_fails(monkeypatch, tmp_path: Path) -> None:
    import dashboard.demo_api as demo_api

    _configure_virtual_state(monkeypatch, tmp_path)

    def broken_run_ai_command(_message: str) -> dict[str, object]:
        raise RuntimeError("boom")

    monkeypatch.setattr(demo_api, "run_ai_command", broken_run_ai_command)
    response = TestClient(create_app()).post("/api/demo/chat", json={"message": "проверь систему"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "error"
    assert "проверь систему" in payload["reply"]
    assert payload["state"]["mode"] == "VIRTUAL_ACCOUNT"


def test_demo_chat_blocks_virtual_buy_without_creating_trade(monkeypatch, tmp_path: Path) -> None:
    _configure_virtual_state(monkeypatch, tmp_path)
    client = TestClient(create_app())
    before = client.get("/api/demo/state").json()["state"]["trades"]
    response = client.post("/api/demo/chat", json={"message": "купи BTC виртуально"})
    after = client.get("/api/demo/state").json()["state"]["trades"]
    payload = response.json()
    assert response.status_code == 200
    assert payload["status"] == "blocked"
    assert payload["real_orders_blocked"] is True
    assert payload["use"] == "/api/virtual-account/tick"
    assert after == before


def test_demo_chat_blocks_virtual_sell_without_creating_trade(monkeypatch, tmp_path: Path) -> None:
    _configure_virtual_state(monkeypatch, tmp_path)
    client = TestClient(create_app())
    before = client.get("/api/demo/state").json()["state"]["trades"]
    response = client.post("/api/demo/chat", json={"message": "продай BTC"})
    after = client.get("/api/demo/state").json()["state"]["trades"]
    assert response.json()["status"] == "blocked"
    assert after == before


def test_demo_online_monitoring_is_truthful(monkeypatch, tmp_path: Path) -> None:
    _configure_virtual_state(monkeypatch, tmp_path)
    state = TestClient(create_app()).get("/api/demo/state").json()["state"]
    assert state["online_monitoring"]["demo_account_online"] is True
    assert state["online_monitoring"]["exchange_connector_online"] is False
    assert state["online_monitoring"]["real_orders_blocked"] is True
