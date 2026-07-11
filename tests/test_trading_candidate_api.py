from __future__ import annotations

import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard.trading_candidate_api import install_trading_candidate_api


def _candidate() -> dict:
    now = int(time.time() * 1000)
    return {
        "candidate_id": "cand-api-001",
        "symbol": "BTCUSDT",
        "category": "spot",
        "side": "Buy",
        "environment": "testnet",
        "market_timestamp_ms": now - 100,
        "received_timestamp_ms": now - 50,
        "reference_price": 60_000,
        "data_sources": ["bybit-public-ws"],
        "market_regime": "trend",
        "signal_evidence": ["momentum-confirmed"],
        "news_evidence": [],
        "portfolio_snapshot_id": "portfolio-api-001",
        "estimated_fees": 0.1,
        "estimated_slippage": 0.2,
        "risk_score": 20,
        "risk_blocks": [],
        "confidence": 80,
        "consensus": 85,
        "decision": "ALLOW",
        "expires_at_ms": now + 1_000,
    }


def test_candidate_validation_endpoint_is_read_only_and_allows_valid_testnet_candidate():
    app = FastAPI()
    install_trading_candidate_api(app)
    with TestClient(app) as client:
        response = client.post("/api/trading/candidate/validate", json=_candidate())

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["execution_allowed"] is True
    assert body["candidate"]["symbol"] == "BTCUSDT"


def test_candidate_validation_endpoint_fails_closed_on_missing_data():
    app = FastAPI()
    install_trading_candidate_api(app)
    payload = _candidate()
    payload.pop("portfolio_snapshot_id")
    with TestClient(app) as client:
        response = client.post("/api/trading/candidate/validate", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "invalid"
    assert body["execution_allowed"] is False
    assert body["effective_decision"] == "BLOCK"
