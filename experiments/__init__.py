"""Research experiment persistence and promotion policy."""
from .adapters import manifest_for_experiment
from .promotion import (
    PromotionGateEngine,
    PromotionGateReport,
    PromotionPolicy,
    PromotionTarget,
)
from .registry import ExperimentIdentity, ExperimentRegistry

__all__ = [
    "ExperimentIdentity",
    "ExperimentRegistry",
    "PromotionGateEngine",
    "PromotionGateReport",
    "PromotionPolicy",
    "PromotionTarget",
    "manifest_for_experiment",
]
