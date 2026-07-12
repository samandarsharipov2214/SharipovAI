"""Typed domain API over the existing canonical ProjectDatabase.

No second database implementation is introduced. All records are stored through
ProjectDatabase so PostgreSQL remains the production source of truth and SQLite
remains the local/test fallback.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from typing import Any, Mapping

from trading_candidate import (
    MarketRegime,
    TradingCandidate,
    TradingCategory,
    TradingDecision,
    TradingEnvironment,
    TradingSide,
    validate_trading_candidate,
)

from .project_database import ProjectDatabase, VersionConflict


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
        clean_namespace = _identifier(namespace, "namespace")
        clean_key = _identifier(key, "key")
        version = self.database.put_json(
            f"memory.{clean_namespace}",
            clean_key,
            {"value": dict(value), "confidence": confidence},
            expected_version=expected_version,
        )
        return StoredRecord(f"memory.{clean_namespace}", clean_key, version)

    def get_memory(self, *, namespace: str, key: str) -> dict[str, Any] | None:
        return self.database.get_json(
            f"memory.{_identifier(namespace, 'namespace')}",
            _identifier(key, "key"),
        )

    def save_market_quote(self, quote: Mapping[str, Any]) -> str:
        """Persist both canonical and existing MarketQuote payload shapes."""
        payload = dict(quote)
        provider = _identifier(payload.get("provider") or payload.get("source"), "provider")
        symbol = _identifier(payload.get("symbol"), "symbol")
        category = _identifier(payload.get("category", "spot"), "category")
        price = _positive_number(
            payload.get("last_price") if payload.get("last_price") is not None else payload.get("price"),
            "last_price",
        )
        timestamp = _positive_integer(
            payload.get("exchange_timestamp_ms")
            if payload.get("exchange_timestamp_ms") is not None
            else payload.get("received_at_unix_ms"),
            "exchange_timestamp_ms",
        )
        payload.update(
            provider=provider,
            symbol=symbol,
            category=category,
            last_price=price,
            exchange_timestamp_ms=timestamp,
        )
        event_id = f"quote:{provider}:{category}:{symbol}:{timestamp}"
        return self._append_event_idempotent(
            "market",
            "quote",
            f"{provider}:{category}:{symbol}",
            payload,
            event_id=event_id,
        )

    def save_news_event(self, event: Mapping[str, Any]) -> str:
        payload = dict(event)
        source = _identifier(payload.get("source"), "source")
        source_id = _identifier(payload.get("source_event_id"), "source_event_id")
        headline = str(payload.get("headline", "")).strip()
        if not headline:
            raise ValueError("headline is required")
        payload.update(source=source, source_event_id=source_id, headline=headline)
        return self._append_event_idempotent(
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

        event_id = f"portfolio:{environment}:{account_key}:{captured_at_ms}"
        self._append_event_idempotent(
            "portfolio",
            "snapshot",
            f"{environment}:{account_key}",
            payload,
            event_id=event_id,
            created_at_ms=captured_at_ms,
        )

        for _ in range(3):
            current = self.database.get_json("portfolio", key)
            if current:
                current_timestamp = int(current["value"].get("captured_at_ms") or 0)
                if captured_at_ms <= current_timestamp:
                    return StoredRecord("portfolio", key, int(current["version"]))
                expected_version = int(current["version"])
            else:
                expected_version = 0
            try:
                version = self.database.put_json(
                    "portfolio",
                    key,
                    payload,
                    expected_version=expected_version,
                )
                return StoredRecord("portfolio", key, version)
            except VersionConflict:
                continue
        raise VersionConflict("portfolio latest changed repeatedly during monotonic update")

    def save_trading_candidate(self, candidate: Mapping[str, Any] | TradingCandidate) -> StoredRecord:
        payload = candidate.to_dict() if isinstance(candidate, TradingCandidate) else dict(candidate)
        candidate_id = _identifier(payload.get("candidate_id"), "candidate_id")
        environment = _environment(payload.get("environment"), allow_paper=True)
        decision = str(payload.get("decision", "")).strip().upper()
        if decision not in {"ALLOW", "WAIT", "BLOCK"}:
            raise ValueError("candidate decision must be ALLOW, WAIT or BLOCK")
        payload.update(candidate_id=candidate_id, environment=environment, decision=decision)

        if decision == "ALLOW":
            canonical = candidate if isinstance(candidate, TradingCandidate) else _candidate_from_mapping(payload)
            validation = validate_trading_candidate(canonical, now_ms=int(time.time() * 1000))
            if not validation.valid or validation.decision is not TradingDecision.ALLOW:
                raise ValueError("invalid ALLOW candidate: " + "; ".join(validation.errors))

        version = self.database.put_json("trading_candidates", candidate_id, payload)
        self.database.append_event(
            "trading_candidates",
            "decision",
            candidate_id,
            payload,
            event_id=f"candidate:{candidate_id}:v{version}",
        )
        return StoredRecord("trading_candidates", candidate_id, version)

    def append_execution_evidence(self, evidence: Mapping[str, Any]) -> str:
        payload = dict(evidence)
        candidate_id = _identifier(payload.get("candidate_id"), "candidate_id")
        order_link_id = _identifier(payload.get("order_link_id"), "order_link_id")
        environment = _environment(payload.get("environment"), allow_paper=True)
        payload.update(
            candidate_id=candidate_id,
            order_link_id=order_link_id,
            environment=environment,
        )
        revision = _positive_integer(payload.get("revision", 1), "revision")
        return self._append_event_idempotent(
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

    def _append_event_idempotent(
        self,
        namespace: str,
        entity_type: str,
        entity_id: str,
        payload: Mapping[str, Any],
        *,
        event_id: str,
        created_at_ms: int | None = None,
    ) -> str:
        try:
            return self.database.append_event(
                namespace,
                entity_type,
                entity_id,
                dict(payload),
                event_id=event_id,
                created_at_ms=created_at_ms,
            )
        except Exception:
            with self.database.connect() as connection:
                row = self.database._fetchone(
                    connection,
                    "SELECT namespace, entity_type, entity_id, payload_json FROM project_events WHERE event_id = ?",
                    (event_id,),
                )
            if not row:
                raise
            existing = json.loads(row["payload_json"])
            if (
                row["namespace"] != namespace
                or row["entity_type"] != entity_type
                or row["entity_id"] != entity_id
                or existing != dict(payload)
            ):
                raise ValueError(f"event_id collision with different evidence: {event_id}")
            return event_id


def _candidate_from_mapping(payload: Mapping[str, Any]) -> TradingCandidate:
    try:
        return TradingCandidate(
            candidate_id=str(payload["candidate_id"]),
            symbol=str(payload["symbol"]),
            category=TradingCategory(str(payload["category"])),
            side=TradingSide(str(payload["side"])),
            environment=TradingEnvironment(str(payload["environment"])),
            market_timestamp_ms=int(payload["market_timestamp_ms"]),
            received_timestamp_ms=int(payload["received_timestamp_ms"]),
            reference_price=float(payload["reference_price"]),
            data_sources=tuple(payload["data_sources"]),
            market_regime=MarketRegime(str(payload["market_regime"])),
            signal_evidence=tuple(payload["signal_evidence"]),
            news_evidence=tuple(payload.get("news_evidence", ())),
            news_assessment_id=str(payload["news_assessment_id"]),
            portfolio_snapshot_id=str(payload["portfolio_snapshot_id"]),
            cost_snapshot_id=str(payload["cost_snapshot_id"]),
            estimated_fees=float(payload["estimated_fees"]),
            estimated_slippage=float(payload["estimated_slippage"]),
            risk_score=float(payload["risk_score"]),
            risk_blocks=tuple(payload.get("risk_blocks", ())),
            confidence=float(payload["confidence"]),
            consensus=float(payload["consensus"]),
            decision=TradingDecision(str(payload["decision"])),
            expires_at_ms=int(payload["expires_at_ms"]),
            security_approval_id=str(payload.get("security_approval_id", "")),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"incomplete canonical ALLOW candidate: {exc}") from exc


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
