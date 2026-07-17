"""Autonomous market monitoring and staged trading runtime."""
from .canonical_runtime import (
    CanonicalPaperDecisionRuntime,
    CanonicalPaperRuntimeError,
    PaperDecisionAuthorization,
)
from .council_loop import CouncilAuthorizedPaperLoop, CouncilEntryProposal, ProposalProvider
from .council_provider import AutonomousCouncilProposalProvider
from .execution_journal import ExecutionJournal
from .loop import AutonomousPaperLoop
from .market_stream import MarketStream, StreamQuote
from .shadow_bridge import ShadowModeTestnetBridge
from .shadow_mode import ShadowModePlanner, ShadowModePolicy, ShadowOrderPlan
from .shared_market_stream import SharedVerifiedMarketStream
from .stage_controller import StageAssessment, StageController
from .startup_reconciliation import (
    StartupExecutionReconciler,
    StartupReconciliationReport,
)

# Compatibility name now resolves to the bounded shadow-only implementation.
AutonomousTestnetBridge = ShadowModeTestnetBridge

__all__ = (
    "AutonomousCouncilProposalProvider",
    "AutonomousPaperLoop",
    "AutonomousTestnetBridge",
    "CanonicalPaperDecisionRuntime",
    "CanonicalPaperRuntimeError",
    "CouncilAuthorizedPaperLoop",
    "CouncilEntryProposal",
    "ExecutionJournal",
    "MarketStream",
    "PaperDecisionAuthorization",
    "ProposalProvider",
    "ShadowModePlanner",
    "ShadowModePolicy",
    "ShadowModeTestnetBridge",
    "ShadowOrderPlan",
    "SharedVerifiedMarketStream",
    "StageAssessment",
    "StageController",
    "StartupExecutionReconciler",
    "StartupReconciliationReport",
    "StreamQuote",
)
