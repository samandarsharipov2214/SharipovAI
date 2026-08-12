from __future__ import annotations

import pytest

from trading_core.alpha_experiment import AlphaExperiment


def _experiment(**changes: object) -> AlphaExperiment:
    values: dict[str, object] = {
        "experiment_id": "alpha-001",
        "git_sha": "a" * 40,
        "dataset_manifest_sha256": "b" * 64,
        "strategy": "trend",
        "parameters": {"short_window": 20},
        "cost_config": {"fee_rate": 0.001},
        "risk_config": {"max_position_percent": 20},
        "execution_timing": "next_event",
        "train_range": (1, 100),
        "validation_ranges": ((101, 200),),
        "final_oos_range": (201, 300),
        "benchmarks": ("buy_and_hold", "breakout", "mean_reversion"),
        "acceptance_metrics": ("net_expectancy", "profit_factor", "max_drawdown"),
    }
    values.update(changes)
    return AlphaExperiment(**values)  # type: ignore[arg-type]


def test_alpha_preregistration_has_stable_content_fingerprint() -> None:
    assert _experiment().fingerprint() == _experiment().fingerprint()
    assert _experiment(parameters={"short_window": 21}).fingerprint() != _experiment().fingerprint()


def test_alpha_preregistration_rejects_overlapping_final_holdout() -> None:
    with pytest.raises(ValueError, match="final OOS"):
        _experiment(final_oos_range=(200, 300))


def test_alpha_preregistration_rejects_same_event_final_evaluation() -> None:
    with pytest.raises(ValueError, match="same_event"):
        _experiment(execution_timing="same_event")
