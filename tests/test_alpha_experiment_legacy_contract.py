"""Incomplete/legacy preregistrations cannot silently become Alpha evidence."""
from __future__ import annotations

import pytest

from trading_core.alpha_experiment import AlphaExperiment


def test_missing_hypothesis_or_falsification_fields_fail_closed() -> None:
    payload = {
        "experiment_id": "legacy-alpha",
        "git_sha": "a" * 40,
        "dataset_manifest_sha256": "b" * 64,
        "strategy": "regime_filtered_breakout_v1",
        "parameters": {"window": 24},
        "cost_config": {"fee_rate": 0.001},
        "risk_config": {"initial_cash": 10_000.0},
        "execution_timing": "auto",
        "train_range": [100, 199],
        "validation_ranges": [[200, 299]],
        "final_oos_range": [300, 399],
        "benchmarks": ["buy_and_hold"],
        "acceptance_metrics": ["minimum_organic_closed_trades=30"],
    }

    with pytest.raises(ValueError, match="missing hypothesis"):
        AlphaExperiment.from_dict(payload)

    payload["hypothesis"] = "candidate hypothesis"
    with pytest.raises(ValueError, match="missing falsification_rule"):
        AlphaExperiment.from_dict(payload)
