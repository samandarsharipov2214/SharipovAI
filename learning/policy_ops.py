"""Operations runner for policy monitor pipeline."""

from __future__ import annotations

from typing import Any

from .legal_feed_fetcher import run_legal_monitor_cycle
from .legal_source_watcher import LegalWatchStateStore
from .policy_journal import PolicyJournal


def run_policy_ops(
    *,
    watch_store: LegalWatchStateStore,
    journal: PolicyJournal,
    items: list[dict[str, Any]] | None = None,
    feeds: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run monitor cycle and persist useful results."""

    cycle = run_legal_monitor_cycle(feeds=feeds or [], store=watch_store, fetched_items=items or [])
    alerts = [alert for alert in cycle.get("watch", {}).get("alerts", []) if alert.get("status") == "ok"]
    journal_result = journal.add(alerts, cycle.get("controller_advice", {}))
    return {"status": "ok", "cycle": cycle, "journal": journal_result, "snapshot": journal.snapshot()}
