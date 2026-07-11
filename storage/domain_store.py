"""Typed domain API over the existing canonical ProjectDatabase.

No second database implementation is introduced. All records are stored through
ProjectDatabase so PostgreSQL remains the production source of truth and SQLite
remains the local/test fallback.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

from .project_database import ProjectDatabase


@dataclass(frozen=True)
class StoredRecord:
    namespace: str
    key: str
    version: int


class ProjectDomainStore:
    """Canonical persistence facade for all SharipovAI domains."""

    def __init__(self, database: ProjectDatabase | None = None) -> None:
        self.database = database or ProjectDatabase()

    def initialize(self) -> None:
        self.database.initialize()

    def health(self) -> dict[str, Any]:
        return self.database.health()

    def put_memory(
        self,
        *,
        namespace: str,
        key: str,
        value: Mapping[str, Any],
        confidence: float = 100.0,
        expected_version: int | None = None,
    ) -> StoredRecord:
        confidence = _bounded_number(confidence, "confidence", minimum=0, maximum=100)
        version = self.database.put_json(
            f"memory.{_identifier(namespace, 'namespace')}",
            _identifier(key, "key"),
            {"value": dict(value), "confidence": confidence},
            expected_version=expected_version,
        )
        return StoredRecord(f"memory.{namespace}", key, version)

    def get_memory(self, *, namespace: str, key: str) -> dict[str, Any] | None:
        return self.database.get_json(f"memory.{_identifier(namespace, 'namespace')}", _identifier(key, "key"))

    def save_market_quote(self, quote: Mapping[str, Any]) -> str:
        payload = dict(quote)
        provider = _identifier(payload.get("provider"), "provider")
        symbol = _identifier(payload.get("symbol"), "symbol")
        category = _identifier(payload.get("category", "spot"), "category")
        price = _positive_number(payload.get("last_price"), "last_price")
        timestamp = _positive_integer(payload.get("exchange_timestamp_ms"), "exchange_timestamp_ms")
        payload.update(
            provider=provider,
            symbol=symbol,
            category=category,
            last_price=price,
            exchange_timestamp_ms=timestamp,
        )
        return self.database.append_event(
            "market",
            "quote",
            f"{provider}:{category}:{symbol}",
            payload,
            event_id=f"quote:{provider}:{category}:{symbol}:{timestamp}",
        )

    def save_news_event(self, event: Mapping[str, Any]) -> str:
        payload = dict(event)
        source = _identifier(payload.get("source"), "source")
        source_id = _identifier(payload.get("source_event_id"), "source_event_id")
        headline = str(payload.get("headline", "")).strip()
        if not headline:
            raise ValueError("headline is required")
        payload.update(source=source, source_event_id=source_id, headline=headline)
        return self.database.append_event(
            "news",
            "event",
            f"{source}:{source_id}",
            payload,
            event_id=f"news:{source}:{source_id}",
        )

    def save_portfolio_snapshot(
        self,
        *,
        environment: str,
        account_key: str,
        snapshot: Mapping[str, Any],
        captured_at_ms: int,
    ) -> StoredRecord:
        environment = _environment(environment, allow_paper=True)
        account_key = _identifier(account_key, "account_key")
        captured_at_ms = _positive_integer(captured_at_ms, "captured_at_ms")
        key = f"{environment}:{account_key}:latest"
        payload = dict(snapshot)
        payload.update(environment=environment, account_key=account_key, captured_at_ms=captured_at_ms)
        version = self.database.put_json("portfolio", key, payload)
        self.database.append_event(
            "portfolio",
            "snapshot",
            f"{environment}:{account_key}",
            payload,
            event_id=f"portfolio:{environment}:{account_key}:{captured_at_ms}",
            created_at_ms=captured_at_ms,
        )
        return StoredRecord("portfolio", key, version)

    def save_trading_candidate(self, candidate: Mapping[str, Any]) -> StoredRecord:
        payload = dict(candidate)
        candidate_id = _identifier(payload.get("candidate_id"), "candidate_id")
        environment = _environment(payload.get("environment"), allow_paper=True)
        decision = str(payload.get("decision", "")).strip().upper()
        if decision not in {"ALLOW", "BLOCK"}:
            raise ValueError("candidate decision must be ALLOW or BLOCK")
        payload.update(candidate_id=candidate_id, environment=environment, decision=decision)
        version = self.database.put_json("trading_candidates", candidate_id, payload)
        self.database.append_event(
            "trading_candidates",
            "decision",
            candidate_id,
            payload,
            event_id=f"candidate:{candidate_id}",
        )
        return StoredRecord("trading_candidates", candidate_id, version)

    def append_execution_evidence(self, evidence: Mapping[str, Any]) -> str:
        payload = dict(evidence)
        candidate_id = _identifier(payload.get("candidate_id"), "candidate_id")
        order_link_id = _identifier(payload.get("order_link_id"), "order_link_id")
        environment = _environment(payload.get("environment"), allow_paper=False)
        payload.update(
            candidate_id=candidate_id,
            order_link_id=order_link_id,
            environment=environment,
        )
        revision = _positive_integer(payload.get("revision", 1), "revision")
        return self.database.append_event(
            "execution",
            "order_evidence",
            order_link_id,
            payload,
            event_id=f"execution:{environment}:{order_link_id}:{revision}",
        )

    def append_audit(
        self,
        *,
        event_type: str,
        severity: str,
        payload: Mapping[str, Any],
        correlation_id: str,
    ) -> str:
        event_type = _identifier(event_type, "event_type")
        correlation_id = _identifier(correlation_id, "correlation_id")
        severity = str(severity).strip().lower()
        if severity not in {"info", "warning", "error", "critical"}:
            raise ValueError("unsupported audit severity")
        body = dict(payload)
        body.update(event_type=event_type, severity=severity, correlation_id=correlation_id)
        return self.database.append_event("audit", event_type, correlation_id, body)


def _identifier(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    if len(text) > 255:
        raise ValueError(f"{field} is too long")
    return text


def _positive_integer(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a positive integer")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a positive integer") from exc
    if number <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return number


def _positive_number(value: Any, field: str) -> float:
    return _bounded_number(value, field, minimum=0, exclusive_minimum=True)


def _bounded_number(
    value: Any,
    field: str,
    *,
    minimum: float,
    maximum: float | None = None,
    exclusive_minimum: bool = False,
) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    if (exclusive_minimum and number <= minimum) or (not exclusive_minimum and number < minimum):
        raise ValueError(f"{field} is below the safe minimum")
    if maximum is not None and number > maximum:
        raise ValueError(f"{field} exceeds the safe maximum")
    return number


def _environment(value: Any, *, allow_paper: bool) -> str:
    normalized = str(value or "").strip().lower()
    aliases = {"sandbox": "testnet", "live": "mainnet"}
    normalized = aliases.get(normalized, normalized)
    allowed = {"testnet", "mainnet"}
    if allow_paper:
        allowed.add("paper")
    if normalized not in allowed:
        raise ValueError("unsupported environment")
    return normalized
