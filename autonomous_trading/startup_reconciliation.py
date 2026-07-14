"""Fail-closed startup reconciliation for guarded testnet execution."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from storage import ProjectDatabase

from exchange_connector.bybit_order_state import BybitOrderStateStore
from exchange_connector.execution_idempotency import ExecutionIdempotencyRepository

from .execution_journal import ExecutionJournal

_TERMINAL = {
    "Filled",
    "Cancelled",
    "Rejected",
    "Deactivated",
    "PartiallyFilledCanceled",
}


@dataclass(frozen=True, slots=True)
class StartupReconciliationReport:
    status: str
    restart_safe: bool
    environment: str
    reservation_count: int
    private_order_count: int
    journal_order_count: int
    synchronized_order_link_ids: tuple[str, ...]
    unresolved_order_link_ids: tuple[str, ...]
    errors: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class StartupExecutionReconciler:
    """Compare identity reservations, private state and execution journal."""

    def __init__(
        self,
        *,
        database: ProjectDatabase | None = None,
        idempotency: ExecutionIdempotencyRepository | None = None,
        private_orders: BybitOrderStateStore | None = None,
        journal: ExecutionJournal | None = None,
        environment: str = "testnet",
    ) -> None:
        self.database = database or ProjectDatabase()
        self.database.initialize()
        self.environment = environment
        self.idempotency = idempotency or ExecutionIdempotencyRepository(
            database=self.database,
            environment=environment,
        )
        self.private_orders = private_orders or BybitOrderStateStore(
            database=self.database,
            environment=environment,
        )
        self.journal = journal or ExecutionJournal(database=self.database)

    def reconcile(self) -> StartupReconciliationReport:
        identity = self.idempotency.snapshot()
        private = self.private_orders.snapshot()
        journal_rows = list(self.journal.load().get("orders", []))

        reservations = [
            dict(item)
            for item in identity.get("reservations", [])
            if isinstance(item, Mapping)
        ]
        private_rows = [
            dict(item)
            for item in private.get("managed_orders", [])
            if isinstance(item, Mapping)
        ]
        private_by_link = {
            str(item.get("order_link_id", "")): item
            for item in private_rows
            if str(item.get("order_link_id", ""))
        }
        journal_by_link = _latest_journal_by_link(journal_rows)

        errors: list[str] = []
        synchronized: list[str] = []
        unresolved: list[str] = []
        reservation_links = {
            str(item.get("order_link_id", ""))
            for item in reservations
            if str(item.get("order_link_id", ""))
        }

        for reservation in reservations:
            link = str(reservation.get("order_link_id", ""))
            if not link:
                errors.append("idempotency reservation has no orderLinkId")
                continue
            private_order = private_by_link.get(link)
            journal_order = journal_by_link.get(link)

            if private_order is not None:
                try:
                    self.idempotency.sync_private_state(
                        order_link_id=link,
                        status=str(private_order.get("status", "")),
                        cum_exec_qty=float(private_order.get("cum_exec_qty", 0.0) or 0.0),
                        order_id=str(private_order.get("order_id", "")),
                        updated_at_ms=int(private_order.get("updated_time_ms", 0) or 0),
                    )
                    synchronized.append(link)
                    reservation = self.idempotency.record_for(link) or reservation
                except Exception as exc:
                    errors.append(
                        f"cannot synchronize private state for {link}: "
                        f"{type(exc).__name__}: {exc}"
                    )

            status = str(reservation.get("status", ""))
            if journal_order is None and status != "Reserved":
                errors.append(f"execution journal evidence is missing for {link}")
            if private_order is None and status not in _TERMINAL:
                unresolved.append(link)
                errors.append(
                    f"unresolved {status or 'unknown'} reservation has no private order evidence: {link}"
                )
            if private_order is not None:
                private_order_id = str(private_order.get("order_id", ""))
                reserved_order_id = str(reservation.get("order_id", ""))
                if reserved_order_id and private_order_id and reserved_order_id != private_order_id:
                    errors.append(f"orderId mismatch for {link}")
                if journal_order is not None:
                    journal_order_id = str(
                        journal_order.get("order_id")
                        or journal_order.get("orderId")
                        or ""
                    )
                    if journal_order_id and private_order_id and journal_order_id != private_order_id:
                        errors.append(f"journal/private orderId mismatch for {link}")

        for private_order in private_rows:
            link = str(private_order.get("order_link_id", ""))
            if link and link not in reservation_links:
                errors.append(f"managed private order has no idempotency reservation: {link}")

        final_identity = self.idempotency.snapshot()
        final_unresolved = {
            str(item.get("order_link_id", ""))
            for item in final_identity.get("unresolved", [])
            if str(item.get("order_link_id", ""))
        }
        unresolved = sorted(set(unresolved) | final_unresolved)
        restart_safe = not errors and not unresolved
        return StartupReconciliationReport(
            status="ok" if restart_safe else "blocked",
            restart_safe=restart_safe,
            environment=self.environment,
            reservation_count=len(reservations),
            private_order_count=len(private_rows),
            journal_order_count=len(journal_rows),
            synchronized_order_link_ids=tuple(sorted(set(synchronized))),
            unresolved_order_link_ids=tuple(unresolved),
            errors=tuple(errors),
        )

    def assert_restart_safe(self) -> StartupReconciliationReport:
        report = self.reconcile()
        if not report.restart_safe:
            details = "; ".join(report.errors) or "unresolved execution state"
            raise RuntimeError(f"startup reconciliation blocked execution: {details}")
        return report


def _latest_journal_by_link(rows: list[Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        link = str(raw.get("order_link_id") or raw.get("orderLinkId") or "").strip()
        if not link:
            continue
        current = result.get(link)
        timestamp = int(raw.get("recorded_at_ms", 0) or 0)
        current_timestamp = int(current.get("recorded_at_ms", 0) or 0) if current else -1
        if current is None or timestamp >= current_timestamp:
            result[link] = dict(raw)
    return result


__all__ = [
    "StartupExecutionReconciler",
    "StartupReconciliationReport",
]
