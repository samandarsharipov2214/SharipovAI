"""Tests for dashboard safe exchange API endpoints."""

from __future__ import annotations

import pytest
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


def test_exchange_costs_endpoint_returns_ai_cost_report() -> None:
    """Cost endpoint should expose fee, borrow, VIP, and best venue data."""

    response = TestClient(create_app()).get("/api/exchange/costs")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    costs = payload["costs"]
    assert costs["fees"]["spot"]
    assert costs["borrow_rates"]
    assert costs["best_trade_venue"]["best"]["round_trip_fee"] >= 0
    assert costs["vip_progress"]["requirements"]


def test_exchange_cost_estimate_endpoint_counts_trade_and_borrow_cost() -> None:
    """Estimate endpoint should combine trading fees, borrow interest, and best venue."""

    response = TestClient(create_app()).post(
        "/api/exchange/costs/estimate",
        json={
            "notional": 500,
            "product": "futures",
            "liquidity": "maker",
            "borrow_symbol": "USDT",
            "borrow_amount": 500,
            "borrow_hours": 24,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["trade_cost"]["round_trip_fee"] == pytest.approx(0.36)
    assert payload["borrow_cost"]["estimated_interest"] == pytest.approx(500 * 0.0000042903 * 24)
    assert payload["best_trade_venue"]["best"]["round_trip_fee"] >= 0


def test_exchange_fees_and_borrow_rates_endpoints() -> None:
    """Separate fee and borrow endpoints should be available for Mini App."""

    client = TestClient(create_app())
    fees = client.get("/api/exchange/fees").json()
    borrows = client.get("/api/exchange/borrow-rates").json()

    assert fees["status"] == "ok"
    assert fees["fees"]["futures"][0]["maker"] == pytest.approx(0.00036)
    assert borrows["status"] == "ok"
    assert any(item["symbol"] == "BTC" for item in borrows["borrow_rates"])


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
    assert preview["entry_fee"] == pytest.approx(0.1)
    assert preview["expected_exit_fee"] == pytest.approx(0.101)
    assert preview["total_fees"] == pytest.approx(0.201)
    assert preview["gross_result"] == pytest.approx(1.0)
    assert preview["net_result_after_fees"] == pytest.approx(0.799)
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
