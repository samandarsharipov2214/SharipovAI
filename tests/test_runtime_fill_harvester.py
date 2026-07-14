from __future__ import annotations

from exchange_connector.bybit_order_state import BybitOrderStateStore
from storage import ProjectDatabase
from validation.fill_divergence import DivergenceThresholds, FillDivergenceAnalyzer
from validation.runtime_fill_harvester import RuntimeFillHarvester


def _database(tmp_path) -> ProjectDatabase:
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'project.db'}")
    database.initialize()
    return database


def test_harvester_builds_and_persists_paper_testnet_divergence(tmp_path) -> None:
    database = _database(tmp_path)
    private = BybitOrderStateStore(database=database, environment="testnet")
    analyzer = FillDivergenceAnalyzer(
        DivergenceThresholds(
            minimum_matches=1,
            maximum_p95_latency_divergence_ms=500.0,
            maximum_p95_slippage_divergence_bps=5.0,
            maximum_partial_fill_rate_percent=1.0,
            maximum_fill_ratio_delta=0.01,
            maximum_fee_delta_bps=1.0,
        )
    )
    harvester = RuntimeFillHarvester(
        database=database,
        private_orders=private,
        analyzer=analyzer,
    )
    trade_id = "paper-shadow-1"
    order_link_id = "sai_shadow_order_1"
    database.put_json(
        harvester.paper_namespace,
        trade_id,
        {
            "trade_id": trade_id,
            "candidate_id": "paper-candidate-1",
            "created_at_ms": 1_000_000,
            "symbol": "BTCUSDT",
            "side": "BUY",
            "price": 50_000.0,
            "quantity": 0.0005,
            "notional": 25.0,
            "entry_fee": 0.015,
        },
        expected_version=0,
    )
    database.put_json(
        harvester.bridge_namespace,
        trade_id,
        {
            "paper_trade_id": trade_id,
            "experiment_id": "exp-shadow-1",
            "status": "accepted",
            "recorded_at_ms": 1_000_010,
            "symbol": "BTCUSDT",
            "side": "BUY",
            "mirrored_quantity": 0.0005,
            "order_link_id": order_link_id,
            "trading_reference": {
                "reference_price": 50_000.0,
                "taker_fee_rate": 0.0006,
            },
        },
        expected_version=0,
    )
    private.ingest_message(
        {
            "id": "message-shadow-1",
            "topic": "order.spot",
            "creationTime": 1_000_100,
            "data": [
                {
                    "category": "spot",
                    "orderId": "order-shadow-1",
                    "orderLinkId": order_link_id,
                    "symbol": "BTCUSDT",
                    "side": "Buy",
                    "orderStatus": "Filled",
                    "qty": "0.0005",
                    "cumExecQty": "0.0005",
                    "avgPrice": "50000",
                    "createdTime": 1_000_000,
                    "updatedTime": 1_000_100,
                    "rejectReason": "",
                }
            ],
        },
        received_at_ms=1_000_100,
    )

    result = harvester.harvest(
        experiment_id="exp-shadow-1",
        now_ms=1_000_200,
    )

    assert result["status"] == "saved"
    assert result["matched_count"] == 1
    assert result["promotion_eligible"] is True
    assert result["unmatched_paper_count"] == 0
    assert result["unmatched_testnet_count"] == 0

    unchanged = harvester.harvest(
        experiment_id="exp-shadow-1",
        now_ms=1_000_300,
    )
    assert unchanged["status"] == "unchanged"
    assert unchanged["report_id"] == result["report_id"]
