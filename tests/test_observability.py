from __future__ import annotations

import json
import logging
from io import StringIO

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard.routers.metrics import router as metrics_router
from observability.structured_logging import JsonFormatter


def test_json_formatter_emits_fields_and_redacts_secrets() -> None:
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("test.structured")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)

    logger.info(
        "execution checked",
        extra={
            "event": "execution_checked",
            "candidate_id": "candidate-1",
            "context": {"api_key": "secret-value", "symbol": "BTCUSDT"},
        },
    )

    payload = json.loads(stream.getvalue())
    assert payload["event"] == "execution_checked"
    assert payload["candidate_id"] == "candidate-1"
    assert payload["context"]["api_key"] == "[REDACTED]"
    assert payload["context"]["symbol"] == "BTCUSDT"


def test_prometheus_endpoint_is_scrapeable_in_local_mode(monkeypatch) -> None:
    monkeypatch.delenv("SHARIPOVAI_METRICS_TOKEN", raising=False)
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    app = FastAPI()
    app.include_router(metrics_router)

    with TestClient(app) as client:
        response = client.get("/metrics")

    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    assert "sharipovai_http_requests_total" in response.text

def test_http_path_labels_bound_crypto_cardinality() -> None:
    from observability.metrics import _bounded_label, _bounded_path, observe_http

    assert _bounded_path("/api/market/quote/BTCUSDT") == "/api/market/quote/:id"
    assert _bounded_path("/api/market/candles/ethusdt") == "/api/market/candles/:id"
    assert _bounded_path("/api/users/42/profile") == "/api/users/:id/profile"
    assert (
        _bounded_path("/api/items/550e8400-e29b-41d4-a716-446655440000")
        == "/api/items/:id"
    )
    assert _bounded_path("/api/release/status") == "/api/release/status"
    assert _bounded_label("dataset/../raw id!") == "dataset_.._raw_id"
    assert _bounded_label("   ") == "unknown"

    observe_http(
        method="GET",
        path="/api/market/quote/SOLUSDT",
        status_code=200,
        duration_seconds=0.01,
    )
    observe_http(
        method="GET",
        path="/api/market/quote/DOGEUSDT",
        status_code=200,
        duration_seconds=0.02,
    )


def test_dataset_validation_metric_labels_are_sanitized() -> None:
    from types import SimpleNamespace

    from observability.metrics import record_dataset_validation

    record_dataset_validation(
        SimpleNamespace(
            dataset_id="hist/../BTCUSDT candles!",
            valid=True,
            row_count=12,
        )
    )

