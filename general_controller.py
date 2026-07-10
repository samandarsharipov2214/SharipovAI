"""General Controller policy layer for existing SharipovAI components."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from architecture_registry import architecture_audit, owner_for


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    capability: str
    owners: tuple[str, ...]
    selected_owner: str | None
    requires_consensus: bool
    allowed: bool
    reason: str


class GeneralController:
    """Routes work to existing owners and blocks accidental duplication."""

    def route(self, capability: str, *, preferred_owner: str | None = None) -> RoutingDecision:
        owners = tuple(owner_for(capability))
        if not owners:
            return RoutingDecision(
                capability=capability,
                owners=(),
                selected_owner=None,
                requires_consensus=False,
                allowed=False,
                reason="No registered owner. Extend an existing component before creating a new AI.",
            )
        if preferred_owner and preferred_owner not in owners:
            return RoutingDecision(
                capability=capability,
                owners=owners,
                selected_owner=None,
                requires_consensus=len(owners) > 1,
                allowed=False,
                reason=f"Preferred owner '{preferred_owner}' does not own this capability.",
            )
        selected = preferred_owner or owners[0]
        return RoutingDecision(
            capability=capability,
            owners=owners,
            selected_owner=selected,
            requires_consensus=len(owners) > 1,
            allowed=True,
            reason="Existing capability owner selected; no duplicate AI created.",
        )

    def approve_architecture_change(self, proposed_capabilities: list[str]) -> dict[str, Any]:
        conflicts = {
            capability: owner_for(capability)
            for capability in proposed_capabilities
            if owner_for(capability)
        }
        audit = architecture_audit()
        allowed = not conflicts and audit["status"] == "ok"
        return {
            "allowed": allowed,
            "conflicts": conflicts,
            "architecture_status": audit["status"],
            "reason": (
                "New ownership is unique and architecture audit is clean."
                if allowed
                else "Extend listed owners instead of adding a duplicate component."
            ),
        }
