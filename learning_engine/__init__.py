"""Learning engine package for SharipovAI OS."""

from .evidence_policy import AgentEvidence, OutcomeEvidence, SelfLearningPolicy
from .exceptions import LearningEngineError
from .learning_engine import LearningEngine
from .models import LearningRecord, LearningSummary
from .outcome_attribution import AgentAttribution, OutcomeAttributionService
from .research_challengers import ChallengerEvaluation, ResearchChallengerService
from .self_learning_supervisor import SelfLearningSupervisor
from .statistics import LearningStatistics

__all__: tuple[str, ...] = (
    "AgentAttribution",
    "AgentEvidence",
    "ChallengerEvaluation",
    "LearningEngine",
    "LearningEngineError",
    "LearningRecord",
    "LearningStatistics",
    "LearningSummary",
    "OutcomeAttributionService",
    "OutcomeEvidence",
    "ResearchChallengerService",
    "SelfLearningPolicy",
    "SelfLearningSupervisor",
)
