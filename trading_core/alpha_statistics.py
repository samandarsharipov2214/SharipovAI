"""Small deterministic uncertainty tools for Alpha evidence.

No external statistics dependency is required. Circular block resampling keeps
adjacent trade outcomes together inside blocks instead of pretending every trade
is iid.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MeanConfidenceInterval:
    lower: float
    upper: float
    confidence: float
    sample_count: int
    block_length: int
    bootstrap_samples: int
    seed: int
    method: str = "circular_block_bootstrap"


def circular_block_bootstrap_mean_ci(
    values: tuple[float, ...] | list[float],
    *,
    confidence: float = 0.95,
    bootstrap_samples: int = 2_000,
    seed: int = 0,
) -> MeanConfidenceInterval | None:
    """Return a deterministic percentile CI for the sequence mean.

    At least two finite observations are required. The block length is the
    rounded square root of sample size, bounded to ``1..n``. Blocks wrap around
    the sequence so every observation has equal chance of appearing near a block
    boundary. This is still an uncertainty diagnostic, not proof of iid returns.
    """

    clean = tuple(float(value) for value in values)
    if len(clean) < 2:
        return None
    if any(not math.isfinite(value) for value in clean):
        raise ValueError("bootstrap values must be finite")
    if not math.isfinite(float(confidence)) or not 0 < confidence < 1:
        raise ValueError("confidence must be within 0..1")
    if (
        isinstance(bootstrap_samples, bool)
        or not isinstance(bootstrap_samples, int)
        or not 100 <= bootstrap_samples <= 100_000
    ):
        raise ValueError("bootstrap_samples must be within 100..100000")

    count = len(clean)
    block_length = min(count, max(1, int(round(math.sqrt(count)))))
    rng = random.Random(seed)
    means: list[float] = []
    for _ in range(bootstrap_samples):
        resampled: list[float] = []
        while len(resampled) < count:
            start = rng.randrange(count)
            for offset in range(block_length):
                resampled.append(clean[(start + offset) % count])
                if len(resampled) == count:
                    break
        means.append(sum(resampled) / count)

    means.sort()
    tail = (1.0 - confidence) / 2.0
    lower_index = max(0, min(bootstrap_samples - 1, int(math.floor(tail * bootstrap_samples))))
    upper_index = max(
        0,
        min(
            bootstrap_samples - 1,
            int(math.ceil((1.0 - tail) * bootstrap_samples)) - 1,
        ),
    )
    return MeanConfidenceInterval(
        lower=means[lower_index],
        upper=means[upper_index],
        confidence=float(confidence),
        sample_count=count,
        block_length=block_length,
        bootstrap_samples=bootstrap_samples,
        seed=int(seed),
    )


__all__ = ["MeanConfidenceInterval", "circular_block_bootstrap_mean_ci"]
