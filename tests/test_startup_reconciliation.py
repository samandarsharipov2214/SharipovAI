from __future__ import annotations

from autonomous_trading.execution_journal import ExecutionJournal
from autonomous_trading.startup_reconciliation import StartupExecutionReconciler
from exchange_connector.bybit_order_state import BybitOrderStateStore
from exchange_connector.execution_contract import build_execution_request
from exchange_connector.execution_idempotency import ExecutionIdempotencyRepository
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
        candidate_id="candidate-reconcile-001",
        symbol="BTCUSDT",
        category=TradingCategory.SPOT,
        side=TradingSide.BUY,
        environment=TradingEnvironment.TESTNET,
        market_timestamp_ms=now_ms - 500,
        received_timestamp_ms=now_ms - 400,
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
    validation = CandidateValidation(True, TradingDecision.ALLOW, (), 70.0, 70.0)
    return build_execution_request(
        candidate,
        validation,
        quantity=0.0002,
        now_ms=now_ms,
    )


def _components(tmp_path):
    database = _database(tmp_path)
    idempotency = ExecutionIdempotencyRepository(database=database)
    private = BybitOrderStateStore(database=database, environment="testnet")
    journal = ExecutionJournal(
        path=str(tmp_path / "execution-journal.json"),
        database=database,
    )
    reconciler = StartupExecutionReconciler(
        database=database,
        idempotency=idempotency,
        private_orders=private,
        journal=journal,
    )
    return idempotency, private, journal, reconciler


def test_empty_execution_state_is_restart_safe(tmp_path) -> None:
    _, _, _, reconciler = _components(tmp_path)

    report = reconciler.reconcile()

    assert report.status == "ok"
    assert report.restart_safe is True
    assert report.errors == ()


def test_submitted_without_private_evidence_blocks_restart(tmp_path) -> None:
    idempotency, _, _, reconciler = _components(tmp_path)
    request = _request()
    idempotency.reserve(request, now_ms=10_000_000)
    idempotency.mark_submitted(request, now_ms=10_000_001)

    report = reconciler.reconcile()

    assert report.status == "blocked"
    assert report.restart_safe is False
    assert request.order_link_id in report.unresolved_order_link_ids
    assert any("private order evidence" in error for error in report.errors)


def test_private_filled_state_synchronizes_and_allows_restart(tmp_path) -> None:
    idempotency, private, journal, reconciler = _components(tmp_path)
    request = _request()
    idempotency.reserve(request, now_ms=10_000_000)
    idempotency.mark_submitted(request, now_ms=10_000_001)
    idempotency.bind_accepted(
        request,
        order_id="order-1",
        now_ms=10_000_002,
    )
    journal.append(
        {
            "journal_event_id": "accepted-order-1",
            "status": "accepted",
            "environment": "testnet",
            "category": "spot",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "quantity": 0.0002,
            "candidate_id": request.candidate_id,
            "order_link_id": request.order_link_id,
            "order_id": "order-1",
        }
    )
    private.ingest_message(
        {
            "id": "message-1",
            "topic": "order.spot",
            "creationTime": 10_000_100,
            "data": [
                {
                    "category": "spot",
                    "orderId": "order-1",
                    "orderLinkId": request.order_link_id,
                    "symbol": "BTCUSDT",
                    "side": "Buy",
                    "orderStatus": "Filled",
                    "qty": "0.0002",
                    "cumExecQty": "0.0002",
                    "avgPrice": "50000",
                    "createdTime": 10_000_000,
                    "updatedTime": 10_000_100,
                    "rejectReason": "",
                }
            ],
        },
        received_at_ms=10_000_100,
    )

    report = reconciler.reconcile()
    record = idempotency.record_for(request.order_link_id)

    assert report.status == "ok"
    assert report.restart_safe is True
    assert request.order_link_id in report.synchronized_order_link_ids
    assert record is not None
    assert record["status"] == "Filled"
    assert record["cum_exec_qty"] == 0.0002
