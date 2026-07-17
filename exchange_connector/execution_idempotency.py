"""Canonical idempotency repository for exchange execution.

The repository adapts the existing :mod:`bybit_order_identity` registry to the
new :class:`ApprovedExecutionRequest` contract. A duplicate or unresolved
financial action is never retried blindly.
"""
from __future__ import annotations

from typing import Any

from storage import ProjectDatabase

from .bybit_order_identity import OrderIntentRegistry
from .execution_contract import ApprovedExecutionRequest, validate_execution_request


class DuplicateExecutionBlocked(RuntimeError):
    """Raised when an identical request already has a durable reservation."""

    def __init__(self, record: dict[str, Any]) -> None:
        self.record = dict(record)
        super().__init__(
            "duplicate execution blocked for orderLinkId "
            f"{self.record.get('order_link_id', '<unknown>')}; reconciliation required"
        )


class ExecutionIdempotencyRepository:
    """Reserve and track canonical execution requests in ProjectDatabase."""

    def __init__(
        self,
        *,
        database: ProjectDatabase | None = None,
        environment: str = "testnet",
    ) -> None:
        self.registry = OrderIntentRegistry(database=database, environment=environment)
        self.environment = self.registry.environment

    def reserve(
        self,
        request: ApprovedExecutionRequest,
        *,
        now_ms: int,
    ) -> dict[str, Any]:
        validate_execution_request(request, now_ms=now_ms)
        intent = request.to_order_intent()
        if intent.environment != self.environment:
            raise ValueError("request environment does not match idempotency repository")
        if intent.order_link_id() != request.order_link_id:
            raise ValueError("request orderLinkId does not match deterministic intent")
        record = self.registry.reserve(intent, created_at_ms=now_ms)
        if bool(record.get("duplicate")):
            raise DuplicateExecutionBlocked(record)
        return record

    def mark_submitted(
        self,
        request: ApprovedExecutionRequest,
        *,
        now_ms: int,
    ) -> dict[str, Any]:
        return self.registry.update_status(
            request.order_link_id,
            status="Submitted",
            cum_exec_qty=0.0,
            updated_at_ms=now_ms,
        )

    def bind_accepted(
        self,
        request: ApprovedExecutionRequest,
        *,
        order_id: str,
        now_ms: int,
    ) -> dict[str, Any]:
        return self.registry.bind_submission(
            request.order_link_id,
            order_id=order_id,
            updated_at_ms=now_ms,
        )

    def mark_rejected(
        self,
        request: ApprovedExecutionRequest,
        *,
        now_ms: int,
    ) -> dict[str, Any]:
        return self.registry.update_status(
            request.order_link_id,
            status="Rejected",
            cum_exec_qty=0.0,
            updated_at_ms=now_ms,
        )

    def sync_private_state(
        self,
        *,
        order_link_id: str,
        status: str,
        cum_exec_qty: float,
        order_id: str = "",
        updated_at_ms: int,
    ) -> dict[str, Any]:
        return self.registry.update_status(
            order_link_id,
            status=status,
            cum_exec_qty=cum_exec_qty,
            updated_at_ms=updated_at_ms,
            order_id=order_id or None,
        )

    def snapshot(self) -> dict[str, Any]:
        return self.registry.snapshot()

    def unresolved(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self.snapshot()["unresolved"]]

    def record_for(self, order_link_id: str) -> dict[str, Any] | None:
        for item in self.snapshot()["reservations"]:
            if item.get("order_link_id") == order_link_id:
                return dict(item)
        return None


__all__ = [
    "DuplicateExecutionBlocked",
    "ExecutionIdempotencyRepository",
]
