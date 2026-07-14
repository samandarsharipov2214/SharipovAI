from __future__ import annotations

import pytest

from experiments import ExperimentRegistry, PromotionGateEngine, PromotionTarget
from storage import ProjectDatabase


def _database(tmp_path) -> ProjectDatabase:
    return ProjectDatabase(f"sqlite:///{tmp_path / 'project.db'}")


def _research_results() -> dict[str, object]:
    windows = [
        {"window_index": index, "result": {"net_pnl": 10.0}}
        for index in range(6)
    ]
    return {
        "walk_forward": {
            "windows": windows,
            "window_count": 6,
            "profitable_window_percent": 100.0,
            "net_pnl": 60.0,
            "return_percent": 0.6,
            "max_drawdown_percent": 2.0,
            "sharpe_ratio": 1.2,
            "sortino_ratio": 1.8,
            "total_fees": 5.0,
            "total_slippage_cost": 2.0,
            "total_funding_cost": 1.0,
            "metadata": {
                "lookahead_allowed": False,
                "fees_included": True,
                "slippage_included": True,
                "market_impact_included": True,
                "funding_included": True,
            },
        },
        "benchmarks": {
            "ranking": [
                "candidate_v1",
                "buy_and_hold",
                "trend_following",
                "breakout",
                "mean_reversion",
            ],
            "metadata": {
                "candidate_name": "candidate_v1",
                "candidate_beats_buy_hold": True,
            },
        },
        "data_validation": {
            "valid": True,
            "material_warnings": [],
        },
    }


def test_experiment_registry_persists_identity_results_and_manual_promotion(tmp_path) -> None:
    registry = ExperimentRegistry(_database(tmp_path))
    created = registry.create(
        experiment_id="exp-candidate-v1",
        commit_sha="9d4ec8a3049a5f39f9d0d73ab4e93caba6af052c",
        manifest={
            "manifest_id": "btc-1m-2024-2026",
            "version": "1",
            "sha256": "a" * 64,
            "validated": True,
        },
        strategy_name="candidate_v1",
        strategy_config={"lookback": 20},
        backtest_config={"fee_rate": 0.001, "slippage_bps": 2.0},
        actor="test" if False else None,
    )

    current = created
    for name, result in _research_results().items():
        current = registry.record_result(
            "exp-candidate-v1",
            name,
            result,
            actor="research-runner",
            expected_version=current["version"],
        )
    completed = registry.complete(
        "exp-candidate-v1",
        actor="research-runner",
        expected_version=current["version"],
    )
    report = PromotionGateEngine().evaluate(
        completed,
        target_stage=PromotionTarget.PAPER,
    ).to_dict()

    assert report["automated_gate_passed"] is True
    pending = registry.save_promotion_report(
        "exp-candidate-v1",
        report,
        actor="general-controller",
        expected_version=completed["version"],
    )
    assert pending["status"] == "promotion_pending"

    promoted = registry.manual_decision(
        "exp-candidate-v1",
        target_stage="paper",
        approve=True,
        actor="owner",
        reason="Reviewed manifest, code, benchmark table and drawdown path",
        approval_token="APPROVE:exp-candidate-v1:paper",
        expected_version=pending["version"],
    )
    assert promoted["status"] == "promoted"
    assert promoted["promotion"]["manual_decision"]["approved"] is True
    assert len(registry.history("exp-candidate-v1")) >= 6


def test_manual_approval_cannot_override_blocked_report(tmp_path) -> None:
    registry = ExperimentRegistry(_database(tmp_path))
    created = registry.create(
        experiment_id="exp-blocked",
        commit_sha="9d4ec8a",
        manifest={"manifest_id": "bad", "version": "1", "validated": False},
        strategy_name="candidate",
        strategy_config={},
        backtest_config={},
    )
    running = registry.record_result(
        "exp-blocked",
        "walk_forward",
        {"window_count": 1, "net_pnl": -10.0},
        actor="runner",
        expected_version=created["version"],
    )
    completed = registry.complete(
        "exp-blocked",
        actor="runner",
        expected_version=running["version"],
    )
    report = PromotionGateEngine().evaluate(
        completed,
        target_stage="paper",
    ).to_dict()
    assert report["eligible_for_manual_approval"] is False
    stored = registry.save_promotion_report(
        "exp-blocked",
        report,
        actor="controller",
        expected_version=completed["version"],
    )

    with pytest.raises(ValueError, match="blocked promotion"):
        registry.manual_decision(
            "exp-blocked",
            target_stage="paper",
            approve=True,
            actor="owner",
            reason="force it",
            approval_token="APPROVE:exp-blocked:paper",
            expected_version=stored["version"],
        )
