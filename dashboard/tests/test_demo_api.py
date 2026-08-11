"""Tests for the legacy demo compatibility surface."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dashboard import create_app


@pytest.fixture(autouse=True)
def _public_dashboard_test_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHARIPOVAI_DISABLE_AUTH", "1")


def test_demo_state_is_funded_by_default(monkeypatch, tmp_path: Path) -> None:
    """Legacy state remains readable for compatibility where canonical state is absent."""

    monkeypatch.setenv("DEMO_STATE_FILE", str(tmp_path / "demo_state.json"))
    client = TestClient(create_app())

    response = client.get("/api/demo/state")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["state"]["equity"] == 10000.0
    assert payload["state"]["cash"] == 10000.0
    assert payload["state"]["open_positions"] == 0
    assert "exchange_status" in payload["state"]
    assert "online_monitoring" in payload["state"]
    assert payload["state"]["online_monitoring"]["demo_account_online"] is True
    assert payload["state"]["online_monitoring"]["real_orders_blocked"] is True


def test_demo_balance_can_be_changed(monkeypatch, tmp_path: Path) -> None:
    """Legacy sandbox balance endpoint remains isolated from canonical paper truth."""

    monkeypatch.setenv("DEMO_STATE_FILE", str(tmp_path / "demo_state.json"))
    client = TestClient(create_app())

    response = client.post("/api/demo/balance", json={"balance": 20000})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload.get("deprecated") is True
    assert payload["state"]["equity"] == 20000.0
    assert payload["state"]["cash"] == 20000.0
    assert "legacy sandbox" in payload["message"]


def test_demo_chat_reports_exchange_costs_without_inventing_trade(monkeypatch, tmp_path: Path) -> None:
    """Cost questions may be answered but must not fabricate a virtual execution."""

    monkeypatch.setenv("DEMO_STATE_FILE", str(tmp_path / "demo_state.json"))
    monkeypatch.setenv("EXCHANGE_MODE", "sandbox")
    client = TestClient(create_app())

    response = client.post("/api/demo/chat", json={"message": "найди выгодные условия Bybit"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["reply"].strip()
    assert "купил" not in payload["reply"].lower()
    assert "продал" not in payload["reply"].lower()


def test_demo_chat_stays_available_when_legacy_engine_is_irrelevant(monkeypatch) -> None:
    """Canonical presentation must not depend on a legacy demo command engine."""

    import dashboard.demo_api as demo_api

    def broken_run_ai_command(_message: str) -> dict[str, object]:
        raise RuntimeError("boom")

    monkeypatch.setattr(demo_api, "run_ai_command", broken_run_ai_command)
    client = TestClient(create_app())

    response = client.post("/api/demo/chat", json={"message": "найди выгодные условия Bybit"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["reply"].strip()


def test_demo_chat_cannot_create_synthetic_buy_from_text(monkeypatch, tmp_path: Path) -> None:
    """Natural-language demo chat is not an alternative execution authority."""

    monkeypatch.setenv("DEMO_STATE_FILE", str(tmp_path / "demo_state.json"))
    monkeypatch.setenv("EXCHANGE_MODE", "sandbox")
    monkeypatch.setenv("EXCHANGE_DEFAULT_FEE_RATE", "0.001")
    client = TestClient(create_app())

    response = client.post("/api/demo/chat", json={"message": "купи BTC виртуально"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert "купил" not in payload["reply"].lower()
    assert "BUY" not in str((payload.get("run") or {}).get("decision", ""))


def test_demo_chat_cannot_create_synthetic_sell_from_text(monkeypatch, tmp_path: Path) -> None:
    """Sell text must not create an independent legacy trade history."""

    monkeypatch.setenv("DEMO_STATE_FILE", str(tmp_path / "demo_state.json"))
    monkeypatch.setenv("EXCHANGE_MODE", "sandbox")
    client = TestClient(create_app())

    response = client.post("/api/demo/chat", json={"message": "продай BTC"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert "продал" not in payload["reply"].lower()
    assert "SELL" not in str((payload.get("run") or {}).get("decision", ""))


def test_demo_chat_monitoring_is_read_only(monkeypatch, tmp_path: Path) -> None:
    """Monitoring questions return text without becoming a trading side effect."""

    monkeypatch.setenv("DEMO_STATE_FILE", str(tmp_path / "demo_state.json"))
    monkeypatch.setenv("EXCHANGE_MODE", "sandbox")
    client = TestClient(create_app())

    response = client.post("/api/demo/chat", json={"message": "мониторинг онлайн биржи"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["reply"].strip()
    assert "BUY" not in str((payload.get("run") or {}).get("decision", ""))
    assert "SELL" not in str((payload.get("run") or {}).get("decision", ""))
