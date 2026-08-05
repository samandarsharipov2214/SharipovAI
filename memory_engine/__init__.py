"""Passive, feature-flagged Memory Layer for SharipovAI."""
from .config import MemorySettings
from .context import MemoryContextProvider
from .extraction import (
    EmbeddingProvider,
    ExtractedFact,
    FactExtractor,
    JSONCompletionClient,
    OpenAICompatibleEmbeddingProvider,
    OpenAICompatibleJSONClient,
)
from .learning_bridge import DevelopmentLearningMemoryBridge
from .migrations import MEMORY_SCHEMA_VERSION, MemoryMigrationManager
from .models import (
    ApprovalRequest,
    ContextItem,
    ContextRequest,
    FactCreate,
    MemoryFact,
    MemoryStatus,
    RawLog,
    RawLogCreate,
    RawLogStatus,
)
from .repository import MemoryRepository, SearchHit
from .runtime import MemoryRuntime
from .service import MemoryService
from .verification import FactVerifier, VerificationResult

__all__ = [
    "ApprovalRequest",
    "ContextItem",
    "ContextRequest",
    "DevelopmentLearningMemoryBridge",
    "EmbeddingProvider",
    "ExtractedFact",
    "FactCreate",
    "FactExtractor",
    "FactVerifier",
    "JSONCompletionClient",
    "MEMORY_SCHEMA_VERSION",
    "MemoryContextProvider",
    "MemoryFact",
    "MemoryMigrationManager",
    "MemoryRepository",
    "MemoryRuntime",
    "MemoryService",
    "MemorySettings",
    "MemoryStatus",
    "OpenAICompatibleEmbeddingProvider",
    "OpenAICompatibleJSONClient",
    "RawLog",
    "RawLogCreate",
    "RawLogStatus",
    "SearchHit",
    "VerificationResult",
]
