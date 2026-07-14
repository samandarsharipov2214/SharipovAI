from __future__ import annotations

import httpx
import pytest

from exchange_connector.bybit_execution import BybitExecutionClient
from exchange_connector.execution_contract import build_execution_request
from exchange_connector.execution_idempotency import (
    DuplicateExecutionBlocked,
    ExecutionIdempotencyRepository,
)
from storage import ProjectDatabase
from trading_candidate import (
    CandidateValidation,
    MarketRegime,
    TradingCandidate,
    TradingCategory,
    TradingDecision,
    TradingEnvironment,
    TradingSide,
)


def _database(tmp_path) -> ProjectDatabase:
    return ProjectDatabase(f"sqlite:///{tmp_path / 'project.db'}")


def _request(now_ms: int = 10_000_000):
    candidate = TradingCandidate(
        candidate_id="candidate-idempotent-001",
        symbol="BTCUSDT",
        category=TradingCategory.SPOT,
        side=TradingSide.BUY,
        environment=TradingEnvironment.TESTNET,
        market_timestamp_ms=now_ms - 1_000,
        received_timestamp_ms=now_ms - 900,
        reference_price=50_000.0,
        data_sources=("bybit-ticker", "bybit-orderbook", "binance-cross-check"),
        market_regime=MarketRegime.TREND,
        signal_evidence=("signal-1",),
        news_evidence=(),
        news_assessment_id="news-1",
        portfolio_snapshot_id="portfolio-1",
        cost_snapshot_id="cost-1",
        estimated_fees=0.1,
        estimated_slippage=0.1,
        risk_score=20.0,
        risk_blocks=(),
        confidence=85.0,
        consensus=85.0,
        decision=TradingDecision.ALLOW,
        expires_at_ms=now_ms + 5_000,
    )
    validation = CandidateValidation(
        valid=True,
        decision=TradingDecision.ALLOW,
        errors=(),
        effective_min_confidence=70.0,
        effective_min_consensus=70.0,
    )
    return build_execution_request(
        candidate,
        validation,
        quantity=0.0002,
        now_ms=now_ms,
    )


def _execution_env(monkeypatch) -> None:
    monkeypatch.setenv("EXCHANGE_MODE", "sandbox")
    monkeypatch.setenv("EXCHANGE_BASE_URL", "https://api-testnet.bybit.com")
    monkeypatch.setenv("BYBIT_TESTNET_API_KEY", "test-key")
    monkeypatch.setenv("BYBIT_TESTNET_API_SECRET", "test-secret")
    monkeypatch.setenv("TESTNET_EXECUTION_ENABLED", "1")
    monkeypatch.setenv("EXECUTION_KILL_SWITCH", "0")
    monkeypatch.setenv("EXECUTION_MAX_NOTIONAL_USDT", "25")


def test_duplicate_reservation_is_blocked(tmp_path) -> None:
    database = _database(tmp_path)
    repository = ExecutionIdempotencyRepository(database=database)
    request = _request()

    first = repository.reserve(request, now_ms=10_000_000)
    assert first["status"] == "Reserved"

    with pytest.raises(DuplicateExecutionBlocked) as error:
        repository.reserve(request, now_ms=10_000_001)

    assert error.value.record["order_link_id"] == request.order_link_id
    assert repository.snapshot()["restart_safe"] is False


def test_successful_submission_binds_exchange_order_id(tmp_path, monkeypatch) -> None:
    _execution_env(monkeypatch)
    database = _database(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v5/order/create"
        payload = __import__("json").loads(request.content)
        assert payload["orderLinkId"].startswith("sai_")
        return httpx.Response(
            200,
            json={
                "retCode": 0,
                "retMsg": "OK",
                "result": {"orderId": "testnet-order-1"},
            },
        )

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = BybitExecutionClient(client=http_client, database=database)
    request = _request()

    result = client.execute(request, now_ms=10_000_000)
    record = client.idempotency.record_for(request.order_link_id)

    assert result.order_id == "testnet-order-1"
    assert result.order_link_id == request.order_link_id
    assert record is not None
    assert record["status"] == "Submitted"
    assert record["order_id"] == "testnet-order-1"

    with pytest.raises(DuplicateExecutionBlocked):
        client.execute(request, now_ms=10_000_001)

    http_client.close()


def test_network_timeout_remains_unresolved_and_blocks_retry(tmp_path, monkeypatch) -> None:
    _execution_env(monkeypatch)
    database = _database(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("network outcome unknown", request=request)

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = BybitExecutionClient(client=http_client, database=database)
    request = _request()

    with pytest.raises(RuntimeError, match="outcome is ambiguous"):
        client.execute(request, now_ms=10_000_000)

    record = client.idempotency.record_for(request.order_link_id)
    assert record is not None
    assert record["status"] == "Submitted"
    assert record["order_id"] == ""
    assert client.status()["restart_safe"] is False

    with pytest.raises(DuplicateExecutionBlocked):
        client.execute(request, now_ms=10_000_001)

    http_client.close()
