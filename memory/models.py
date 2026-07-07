"""Typed memory models for SharipovAI OS."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    """Stored record of an analytical decision.

    Attributes:
        id: Unique decision record identifier.
        timestamp: UTC timestamp for the decision record.
        symbol: Asset or instrument symbol.
        decision: Decision label or status.
        confidence: Confidence score associated with the decision.
        agents: Agent names involved in the decision.
        factor_scores: Factor score details used in the decision.
        reason: Human-readable explanation for the decision.
        result: Optional final result or outcome label.
        profit_loss: Optional profit or loss value associated with the outcome.
        notes: Optional additional notes.
    """

    id: str
    timestamp: datetime
    symbol: str
    decision: str
    confidence: float
    agents: list[str] = field(default_factory=list)
    factor_scores: list[dict[str, Any]] = field(default_factory=list)
    reason: str = ""
    result: str | None = None
    profit_loss: float | None = None
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize the record to a JSON-compatible dictionary.

        Returns:
            JSON-compatible dictionary representation.
        """

        return {
            "id": self.id,
            "timestamp": self.timestamp.astimezone(timezone.utc).isoformat(),
            "symbol": self.symbol,
            "decision": self.decision,
            "confidence": self.confidence,
            "agents": list(self.agents),
            "factor_scores": [dict(score) for score in self.factor_scores],
            "reason": self.reason,
            "result": self.result,
            "profit_loss": self.profit_loss,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> DecisionRecord:
        """Deserialize a record from a dictionary.

        Args:
            payload: Dictionary loaded from JSON storage.

        Returns:
            Parsed decision record.
        """

        return cls(
            id=str(payload.get("id", "")),
            timestamp=_parse_datetime(payload.get("timestamp")),
            symbol=str(payload.get("symbol", "")),
            decision=str(payload.get("decision", "")),
            confidence=float(payload.get("confidence", 0.0)),
            agents=_parse_string_list(payload.get("agents")),
            factor_scores=_parse_factor_scores(payload.get("factor_scores")),
            reason=str(payload.get("reason", "")),
            result=_parse_optional_string(payload.get("result")),
            profit_loss=_parse_optional_float(payload.get("profit_loss")),
            notes=_parse_optional_string(payload.get("notes")),
        )


def _parse_datetime(value: Any) -> datetime:
    """Parse a datetime value from JSON storage."""

    if isinstance(value, datetime):
        return value

    if isinstance(value, str) and value:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    return datetime.now(timezone.utc)


def _parse_string_list(value: Any) -> list[str]:
    """Parse a list of strings from an arbitrary value."""

    if not isinstance(value, list):
        return []

    return [str(item) for item in value]


def _parse_factor_scores(value: Any) -> list[dict[str, Any]]:
    """Parse factor score dictionaries from an arbitrary value."""

    if not isinstance(value, list):
        return []

    return [dict(item) for item in value if isinstance(item, Mapping)]


def _parse_optional_string(value: Any) -> str | None:
    """Parse an optional string value."""

    if value is None:
        return None
    return str(value)


def _parse_optional_float(value: Any) -> float | None:
    """Parse an optional float value."""

    if value is None:
        return None
    return float(value)
