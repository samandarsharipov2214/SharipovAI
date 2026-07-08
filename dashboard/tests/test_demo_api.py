"""Tests for persistent demo account API."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from dashboard import create_app


def test_demo_state_is_funded_by_default(monkeypatch, tmp_path: Path) -> None:
    """Demo state should start funded, not at zero."""

    monkeypatch.setenv("DEMO_STATE_FILE", str(tmp_path / "demo_state.json"))
    client = TestClient(create_app())

    response = client.get("/api/demo/state")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["state"]["equity"] == 10000.0
    assert payload["state"]["cash"] == 10000.0
    assert payload["state"]["open_positions"] == 0


def test_demo_balance_can_be_changed(monkeypatch, tmp_path: Path) -> None:
    """User should be able to change virtual demo balance."""

    monkeypatch.setenv("DEMO_STATE_FILE", str(tmp_path / "demo_state.json"))
    client = TestClient(create_app())

    response = client.post("/api/demo/balance", json={"balance": 20000})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["state"]["equity"] == 20000.0
    assert payload["state"]["cash"] == 20000.0
    assert "20000.00" in payload["message"]


def test_demo_chat_can_buy_virtual_btc(monkeypatch, tmp_path: Path) -> None:
    """AI chat should execute a virtual buy in demo mode."""

    monkeypatch.setenv("DEMO_STATE_FILE", str(tmp_path / "demo_state.json"))
    client = TestClient(create_app())

    response = client.post("/api/demo/chat", json={"message": "купи BTC виртуально"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert "купил" in payload["reply"].lower()
    assert payload["state"]["open_positions"] == 1
    assert payload["state"]["cash"] < 10000.0
    assert payload["state"]["total_fees"] > 0
    assert payload["state"]["trades"][-1]["side"] == "BUY"


def test_demo_chat_can_sell_virtual_position(monkeypatch, tmp_path: Path) -> None:
    """AI chat should close a virtual position in demo mode."""

    monkeypatch.setenv("DEMO_STATE_FILE", str(tmp_path / "demo_state.json"))
    client = TestClient(create_app())

    client.post("/api/demo/chat", json={"message": "купи BTC"})
    response = client.post("/api/demo/chat", json={"message": "продай BTC"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["state"]["open_positions"] == 0
    assert payload["state"]["trades"][-1]["side"] == "SELL"
    assert "закрыл" in payload["reply"].lower()
