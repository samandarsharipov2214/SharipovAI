from __future__ import annotations

import pytest

from campaigns import FinalPromotionReportEngine
from experiments import ExperimentRegistry
from storage import ProjectDatabase


def _database(tmp_path) -> ProjectDatabase:
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'project.db'}")
    database.initialize()
    return database


def _experiment(registry: ExperimentRegistry, experiment_id: str) -> None:
    created = registry.create(
        experiment_id=experiment_id,
        commit_sha="abcdef1",
        manifest={"manifest_id": "btc-1m", "version": "1", "validated": True},
        strategy_name="candidate",
        strategy_config={},
        backtest_config={},
    )
    running = registry.record_result(
        experiment_id,
        "walk_forward",
        {"net_pnl": 1.0},
        actor="test",
        expected_version=created["version"],
    )
    registry.complete(experiment_id, actor="test", expected_version=running["version"])


def test_final_report_requires_completed_campaign(tmp_path) -> None:
    database = _database(tmp_path)
    _experiment(ExperimentRegistry(database), "exp-1")
    database.put_json(
        "testnet_shadow_campaigns",
        "campaign-1",
        {
            "campaign_id": "campaign-1",
            "experiment_id": "exp-1",
            "scope": "spot:testnet",
            "status": "running",
            "metrics": {},
            "last_evidence": {},
        },
        expected_version=0,
    )

    with pytest.raises(ValueError, match="completed campaign"):
        FinalPromotionReportEngine(database).generate("campaign-1", actor="owner")


def test_final_report_is_write_once_and_requires_manual_decision(tmp_path) -> None:
    database = _database(tmp_path)
    _experiment(ExperimentRegistry(database), "exp-1")
    campaign = {
        "campaign_id": "campaign-1",
        "experiment_id": "exp-1",
        "scope": "spot:testnet",
        "status": "completed",
        "metrics": {
            "matched_fill_count": 20,
            "unmatched_paper_count": 0,
            "unmatched_testnet_count": 0,
            "orphan_execution_count": 0,
            "duplicate_order_count": 0,
            "unresolved_order_count": 0,
            "actual_execution_fees": True,
        },
        "failed_gates": [],
        "last_evidence": {
            "fill_validation": {
                "promotion_eligible": True,
                "matched_count": 20,
                "unmatched_paper_count": 0,
                "unmatched_testnet_count": 0,
                "p95_latency_divergence_ms": 100.0,
                "p95_slippage_divergence_bps": 1.0,
                "testnet_partial_fill_rate_percent": 0.0,
                "maximum_fill_ratio_delta": 0.0,
            },
            "startup_reconciliation": {"restart_safe": True},
            "private_stream": {"ready": True},
        },
    }
    database.put_json(
        "testnet_shadow_campaigns",
        "campaign-1",
        campaign,
        expected_version=0,
    )
    engine = FinalPromotionReportEngine(database)

    first = engine.generate("campaign-1", actor="owner", now_ms=1_000_000)
    second = engine.generate("campaign-1", actor="owner", now_ms=1_000_000)

    assert first["report_id"] == second["report_id"]
    assert first["version"] == 1
    assert second["version"] == 1
    assert first["manual_decision_required"] is True
    assert first["runtime_flags_changed"] is False
    assert first["mainnet_enabled"] is False
    assert first["leadership_approval_token"] == "PROMOTE:spot:testnet:exp-1:testnet"
    assert len(first["evidence_sha256"]) == 64
