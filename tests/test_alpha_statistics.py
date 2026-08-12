"""Uncertainty diagnostics must be deterministic and not assume iid trades."""
from __future__ import annotations

import math

import pytest

from trading_core.alpha_statistics import circular_block_bootstrap_mean_ci


def test_block_bootstrap_is_deterministic_and_positive_for_uniform_positive_edge() -> None:
    values = tuple(1.0 for _ in range(36))

    first = circular_block_bootstrap_mean_ci(values)
    second = circular_block_bootstrap_mean_ci(values)

    assert first is not None
    assert second == first
    assert first.lower == 1.0
    assert first.upper == 1.0
    assert first.block_length == 6
    assert first.bootstrap_samples == 2_000
    assert first.seed == 0
    assert first.method == "circular_block_bootstrap"


def test_short_sample_returns_no_false_precision() -> None:
    assert circular_block_bootstrap_mean_ci(()) is None
    assert circular_block_bootstrap_mean_ci((5.0,)) is None


def test_mixed_sequence_produces_finite_ordered_interval() -> None:
    interval = circular_block_bootstrap_mean_ci(
        (1.0, 1.5, -0.5, 2.0, -1.0, 0.8, 1.1, -0.2, 0.4),
        bootstrap_samples=500,
    )

    assert interval is not None
    assert math.isfinite(interval.lower)
    assert math.isfinite(interval.upper)
    assert interval.lower <= interval.upper
    assert interval.block_length == 3


def test_invalid_bootstrap_inputs_fail_closed() -> None:
    with pytest.raises(ValueError, match="finite"):
        circular_block_bootstrap_mean_ci((1.0, float("nan")))
    with pytest.raises(ValueError, match="confidence"):
        circular_block_bootstrap_mean_ci((1.0, 2.0), confidence=1.0)
    with pytest.raises(ValueError, match="bootstrap_samples"):
        circular_block_bootstrap_mean_ci((1.0, 2.0), bootstrap_samples=10)
