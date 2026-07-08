"""Tests for dashboard safe exchange API endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient

from dashboard import create_app


def test_exchange_status_endpoint_defaults_to_disabled(monkeypatch) -> None:
    """Exchange status endpoint should expose safety gates without secrets."""

    monkeypatch.delenv("EXCHANGE_MODE", raising=False)
    client = TestClient(create_app())

    response = client.get("/api/exchange/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["exchange"]["mode"] == "disabled"
    assert payload["exchange"]["can_execute_orders"] is False
    assert "api_key" not in payload["exchange"]
    assert "api_secret" not in payload["exchange"]


def test_exchange_preview_order_counts_commissions(monkeypatch) -> None:
    """Preview endpoint should return net result after commissions."""

    monkeypatch.setenv("EXCHANGE_MODE", "sandbox")
    monkeypatch.setenv("EXCHANGE_DEFAULT_FEE_RATE", "0.001")
    client = TestClient(create_app())

    response = client.post(
        "/api/exchange/preview-order",
        json={
            "symbol": "BTCUSDT",
            "side": "BUY",
            "quantity": 1,
            "price": 100.0,
            "expected_exit_price": 101.0,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    preview = payload["preview"]
    assert preview["entry_fee"] == 0.1
    assert preview["expected_exit_fee"] == 0.101
    assert preview["total_fees"] == 0.201
    assert preview["gross_result"] == 1.0
    assert preview["net_result_after_fees"] == 0.799
    assert preview["commission_counted_as_loss"] is True
    assert preview["execution_allowed"] is False


def test_exchange_preview_rejects_bad_order(monkeypatch) -> None:
    """Invalid order payloads should return safe JSON errors."""

    monkeypatch.setenv("EXCHANGE_MODE", "sandbox")
    client = TestClient(create_app())

    response = client.post(
        "/api/exchange/preview-order",
        json={"symbol": "BTCUSDT", "side": "HOLD", "quantity": 1, "price": 100},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "error", "error": "side must be BUY or SELL"}
