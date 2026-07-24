from __future__ import annotations

from experiments import ExperimentRegistry
from storage import ProjectDatabase
from validation import ExpectedPaperFillAnalyzer, Phase12FillValidationService


def _database(tmp_path) -> ProjectDatabase:
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'fill.db'}")
    database.initialize()
    return database


def _rows(count: int = 20):
    expected = []
    paper = []
    testnet = []
    for index in range(count):
        match_id = f"match-{index:02d}"
        submitted = 1_700_000_000_000 + index * 1_000
        reference = 50_000.0 + index
        expected.append({"match_id": match_id, "symbol": "BTCUSDT", "side": "BUY", "submitted_at_ms": submitted, "requested_quantity": 0.001, "reference_price": reference, "expected_fill_price": reference + 1.0, "expected_latency_ms": 100.0, "expected_fee": 0.005})
        paper.append({"match_id": match_id, "order_link_id": match_id, "symbol": "BTCUSDT", "side": "BUY", "submitted_at_ms": submitted, "first_fill_at_ms": submitted + 110, "completed_at_ms": submitted + 120, "requested_quantity": 0.001, "filled_quantity": 0.001, "reference_price": reference, "average_fill_price": reference + 1.2, "fee": 0.005, "status": "Filled"})
        testnet.append({"match_id": match_id, "order_link_id": match_id, "symbol": "BTCUSDT", "side": "BUY", "submitted_at_ms": submitted, "first_fill_at_ms": submitted + 180, "completed_at_ms": submitted + 200, "requested_quantity": 0.001, "filled_quantity": 0.001, "reference_price": reference, "average_fill_price": reference + 1.5, "fee": 0.0055, "status": "Filled"})
    return expected, paper, testnet


def _experiment(registry: ExperimentRegistry) -> str:
    experiment = registry.create(
        experiment_id="fill-exp",
        commit_sha="c" * 40,
        manifest={"manifest_id": "dataset-fill", "version": "v1", "sha256": "d" * 64, "validated": True},
        strategy_name="fill-validation",
        strategy_config={"name": "candidate"},
        backtest_config={"timeframe": "1m"},
        created_at_ms=1_700_000_000_000,
    )
    return str(experiment["experiment_id"])


def test_phase12_combines_expected_paper_and_shadow_testnet_validation(tmp_path) -> None:
    database = _database(tmp_path)
    registry = ExperimentRegistry(database)
    experiment_id = _experiment(registry)
    expected, paper, testnet = _rows()
    report = Phase12FillValidationService(database, experiments=registry).validate(
        experiment_id=experiment_id,
        expected_paper_fills=expected,
        actual_paper_fills=paper,
        testnet_fills=testnet,
        actor="test",
        now_ms=1_700_000_010_000,
    )
    assert report["promotion_eligible"] is True
    assert report["failed_gates"] == []
    assert report["expected_vs_actual_paper"]["matched_count"] == 20
    assert report["paper_vs_testnet_shadow"]["matched_count"] == 20
    assert report["automatic_promotion"] is False
    assert report["manual_decision_required"] is True
    assert "phase12_fill_validation" in registry.get(experiment_id)["results"]


def test_phase12_detects_missing_and_divergent_fills(tmp_path) -> None:
    database = _database(tmp_path)
    registry = ExperimentRegistry(database)
    experiment_id = _experiment(registry)
    expected, paper, testnet = _rows()
    testnet = testnet[:-1]
    testnet[0] = {**testnet[0], "first_fill_at_ms": testnet[0]["submitted_at_ms"] + 10_000, "completed_at_ms": testnet[0]["submitted_at_ms"] + 10_100}
    report = Phase12FillValidationService(database, experiments=registry).validate(
        experiment_id=experiment_id,
        expected_paper_fills=expected,
        actual_paper_fills=paper,
        testnet_fills=testnet,
        actor="test",
        now_ms=1_700_000_020_000,
    )
    assert report["promotion_eligible"] is False
    assert "unmatched_paper_fills" in report["failed_gates"]
    assert report["runtime_flags_changed"] is False


def test_zero_actual_fill_is_not_replaced_by_requested_quantity() -> None:
    expected, paper, _ = _rows()
    paper[0] = {**paper[0], "filled_quantity": 0.0, "fee": 0.0}
    report = ExpectedPaperFillAnalyzer().analyze(
        expected,
        paper,
        created_at_ms=1_700_000_025_000,
    )
    assert report.validation_passed is False
    assert "paper_fill_ratio_error_exceeded" in report.failed_gates
    pair = next(item for item in report.pairs if item["match_id"] == "match-00")
    assert pair["fill_ratio"] == 0.0


def test_phase12_fill_validation_is_idempotent(tmp_path) -> None:
    database = _database(tmp_path)
    registry = ExperimentRegistry(database)
    experiment_id = _experiment(registry)
    expected, paper, testnet = _rows()
    service = Phase12FillValidationService(database, experiments=registry)
    first = service.validate(experiment_id=experiment_id, expected_paper_fills=expected, actual_paper_fills=paper, testnet_fills=testnet, actor="test", now_ms=1_700_000_030_000)
    second = service.validate(experiment_id=experiment_id, expected_paper_fills=expected, actual_paper_fills=paper, testnet_fills=testnet, actor="test", now_ms=1_700_000_040_000)
    assert first["report_id"] == second["report_id"]
    assert second["idempotent"] is True
