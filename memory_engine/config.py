"""Feature flags and bounded runtime settings for the passive Memory Layer."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

_TRUE = {"1", "true", "yes", "on"}


def _truthy(name: str, default: bool = False) -> bool:
    fallback = "1" if default else "0"
    return os.getenv(name, fallback).strip().lower() in _TRUE


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if minimum <= value <= maximum else default


def _bounded_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if minimum <= value <= maximum else default


@dataclass(frozen=True, slots=True)
class MemorySettings:
    """Configuration with every behavior-changing flag disabled by default."""

    enabled: bool = False
    context_injection_enabled: bool = False
    extraction_enabled: bool = False
    verification_enabled: bool = True
    team_id: str = "sharipovai"
    user_id: str = "owner"
    poll_interval_seconds: float = 30.0
    extraction_batch_size: int = 10
    context_limit: int = 5
    search_candidate_limit: int = 100
    max_input_chars: int = 16_000
    max_consecutive_failures: int = 3
    circuit_reset_seconds: int = 300
    llm_base_url: str = ""
    llm_model: str = ""
    llm_api_key: str = field(default="", repr=False)
    embedding_base_url: str = ""
    embedding_model: str = ""
    embedding_api_key: str = field(default="", repr=False)

    @classmethod
    def from_env(cls) -> "MemorySettings":
        return cls(
            enabled=_truthy("MEMORY_ENABLED", False),
            context_injection_enabled=_truthy("MEMORY_CONTEXT_INJECTION", False),
            extraction_enabled=_truthy("MEMORY_EXTRACTION_ENABLED", False),
            verification_enabled=_truthy("MEMORY_VERIFICATION_ENABLED", True),
            team_id=(os.getenv("MEMORY_TEAM_ID", "sharipovai").strip() or "sharipovai")[:200],
            user_id=(os.getenv("MEMORY_USER_ID", "owner").strip() or "owner")[:200],
            poll_interval_seconds=_bounded_float("MEMORY_POLL_INTERVAL_SECONDS", 30.0, 5.0, 3600.0),
            extraction_batch_size=_bounded_int("MEMORY_EXTRACTION_BATCH_SIZE", 10, 1, 100),
            context_limit=_bounded_int("MEMORY_CONTEXT_LIMIT", 5, 1, 20),
            search_candidate_limit=_bounded_int("MEMORY_SEARCH_CANDIDATE_LIMIT", 100, 10, 1000),
            max_input_chars=_bounded_int("MEMORY_MAX_INPUT_CHARS", 16_000, 1000, 100_000),
            max_consecutive_failures=_bounded_int("MEMORY_MAX_CONSECUTIVE_FAILURES", 3, 1, 20),
            circuit_reset_seconds=_bounded_int("MEMORY_CIRCUIT_RESET_SECONDS", 300, 30, 86_400),
            llm_base_url=os.getenv("MEMORY_LLM_BASE_URL", "").strip(),
            llm_model=os.getenv("MEMORY_LLM_MODEL", "").strip(),
            llm_api_key=os.getenv("MEMORY_LLM_API_KEY", "").strip(),
            embedding_base_url=os.getenv("MEMORY_EMBEDDING_BASE_URL", "").strip(),
            embedding_model=os.getenv("MEMORY_EMBEDDING_MODEL", "").strip(),
            embedding_api_key=os.getenv("MEMORY_EMBEDDING_API_KEY", "").strip(),
        )

    def flags(self) -> dict[str, bool]:
        return {
            "MEMORY_ENABLED": self.enabled,
            "MEMORY_CONTEXT_INJECTION": self.context_injection_enabled,
            "MEMORY_EXTRACTION_ENABLED": self.extraction_enabled,
            "MEMORY_VERIFICATION_ENABLED": self.verification_enabled,
        }


__all__ = ["MemorySettings"]
