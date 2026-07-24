from __future__ import annotations

from experiments import ExperimentRegistry
from storage import ProjectDatabase
from validation import Phase12FillValidationService


def test_phase12_report_identity_ignores_observation_order(tmp_path) -> None:
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'identity.db'}")
    database.initialize()
    registry = ExperimentRegistry(database)
    experiment = registry.create(
        experiment_id="identity-exp",
        commit_sha="e" * 40,
        manifest={"manifest_id": "identity-data", "version": "v1", "sha256": "f" * 64, "validated": True},
        strategy_name="identity",
        strategy_config={"name": "candidate"},
        backtest_config={"timeframe": "1m"},
        created_at_ms=1_700_000_000_000,
    )
    expected = []
    paper = []
    testnet = []
    for index in range(20):
        match_id = f"id-{index:02d}"
        submitted = 1_700_000_000_000 + index * 1_000
        price = 40_000.0 + index
        expected.append({"match_id": match_id, "symbol": "BTCUSDT", "side": "BUY", "submitted_at_ms": submitted, "requested_quantity": 0.001, "reference_price": price, "expected_fill_price": price + 1.0, "expected_latency_ms": 100.0, "expected_fee": 0.004})
        paper.append({"match_id": match_id, "symbol": "BTCUSDT", "side": "BUY", "submitted_at_ms": submitted, "first_fill_at_ms": submitted + 100, "completed_at_ms": submitted + 120, "requested_quantity": 0.001, "filled_quantity": 0.001, "reference_price": price, "average_fill_price": price + 1.0, "fee": 0.004, "status": "Filled"})
        testnet.append({"match_id": match_id, "symbol": "BTCUSDT", "side": "BUY", "submitted_at_ms": submitted, "first_fill_at_ms": submitted + 150, "completed_at_ms": submitted + 180, "requested_quantity": 0.001, "filled_quantity": 0.001, "reference_price": price, "average_fill_price": price + 1.2, "fee": 0.0042, "status": "Filled"})
    service = Phase12FillValidationService(database, experiments=registry)
    first = service.validate(
        experiment_id=str(experiment["experiment_id"]),
        expected_paper_fills=expected,
        actual_paper_fills=paper,
        testnet_fills=testnet,
        actor="test",
        now_ms=1_700_000_010_000,
    )
    second = service.validate(
        experiment_id=str(experiment["experiment_id"]),
        expected_paper_fills=list(reversed(expected)),
        actual_paper_fills=list(reversed(paper)),
        testnet_fills=list(reversed(testnet)),
        actor="test",
        now_ms=1_700_000_020_000,
    )
    assert first["report_id"] == second["report_id"]
    assert second["idempotent"] is True
