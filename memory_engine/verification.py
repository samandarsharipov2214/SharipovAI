"""Deterministic verification that never promotes a fact to ACTIVE automatically."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from .models import MemoryFact, MemoryStatus

_DANGEROUS = (
    "disable kill switch",
    "turn off kill switch",
    "enable mainnet",
    "enable live trading",
    "bypass risk",
    "ignore risk",
    "отключить kill switch",
    "выключить kill switch",
    "включить mainnet",
    "включить реальную торговлю",
    "обойти риск",
)
_NEGATIONS = {"not", "never", "no", "не", "нет", "никогда", "нельзя", "запрещено"}
_TOKEN_RE = re.compile(r"[\w-]+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class VerificationResult:
    status: MemoryStatus
    rationale: str
    conflicts: tuple[str, ...] = ()


class FactVerifier:
    """Verify evidence conservatively; manual approval is still required for ACTIVE."""

    def verify(self, fact: MemoryFact, existing: Iterable[MemoryFact]) -> VerificationResult:
        normalized = _normalize(fact.content)
        if any(marker in normalized for marker in _DANGEROUS):
            return VerificationResult(
                MemoryStatus.REVOKED,
                "fact attempts to weaken protected financial controls",
                ("protected_execution_policy",),
            )

        conflicts: list[str] = []
        for current in existing:
            if current.fact_id == fact.fact_id or current.status not in {MemoryStatus.VERIFIED, MemoryStatus.ACTIVE}:
                continue
            current_text = _normalize(current.content)
            if current_text == normalized:
                return VerificationResult(
                    MemoryStatus.SUPERSEDED,
                    "equivalent verified fact already exists",
                    (current.fact_id,),
                )
            if _likely_contradiction(normalized, current_text):
                conflicts.append(current.fact_id)

        if conflicts:
            return VerificationResult(
                MemoryStatus.REVOKED,
                "fact conflicts with existing verified or active memory",
                tuple(conflicts),
            )
        return VerificationResult(
            MemoryStatus.VERIFIED,
            "deterministic checks passed; ACTIVE still requires manual approval",
        )


def _likely_contradiction(left: str, right: str) -> bool:
    left_tokens = set(_TOKEN_RE.findall(left))
    right_tokens = set(_TOKEN_RE.findall(right))
    if not left_tokens or not right_tokens:
        return False
    shared = (left_tokens - _NEGATIONS) & (right_tokens - _NEGATIONS)
    overlap = len(shared) / max(min(len(left_tokens), len(right_tokens)), 1)
    left_negative = bool(left_tokens & _NEGATIONS)
    right_negative = bool(right_tokens & _NEGATIONS)
    return overlap >= 0.65 and left_negative != right_negative


def _normalize(value: str) -> str:
    return " ".join(str(value).strip().lower().split())


__all__ = ["FactVerifier", "VerificationResult"]
