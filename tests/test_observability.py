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
