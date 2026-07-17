"""Research experiment persistence, execution and promotion policy."""
from .adapters import manifest_for_experiment
from .champion_challenger import ChampionChallengerRegistry, LeadershipDecision
from .promotion import (
    PromotionGateEngine,
    PromotionGateReport,
    PromotionPolicy,
    PromotionTarget,
)
from .registry import ExperimentIdentity, ExperimentRegistry
from .runner import (
    AutomaticExperimentRequest,
    AutomaticExperimentRunner,
    ImmutableExperimentResultStore,
)

__all__ = [
    "AutomaticExperimentRequest",
    "AutomaticExperimentRunner",
    "ChampionChallengerRegistry",
    "ExperimentIdentity",
    "ExperimentRegistry",
    "ImmutableExperimentResultStore",
    "LeadershipDecision",
    "PromotionGateEngine",
    "PromotionGateReport",
    "PromotionPolicy",
    "PromotionTarget",
    "manifest_for_experiment",
]
