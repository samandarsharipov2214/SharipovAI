"""Canonical registry and architecture audit for SharipovAI.

The registry describes components that already exist. It never creates agents.
Routing/source tags used by several specialized News AI are intentionally
shared and are not treated as duplicate business ownership.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from learning.ai_learning_core import BOT_NAMES
from news_monitor.agent_network import AGENTS as NEWS_AGENTS


@dataclass(frozen=True, slots=True)
class CapabilityOwner:
    component_id: str
    display_name: str
    kind: str
    priority: int
    capabilities: tuple[str, ...]
    shared_tags: tuple[str, ...] = ()


CORE_OWNERS: tuple[CapabilityOwner, ...] = (
    CapabilityOwner("general_controller", "General Controller", "ai", 1, ("coordination", "final_control", "dependency_control")),
    CapabilityOwner("market_agent", "Market Agent", "ai", 2, ("market_data", "market_candidates", "market_analysis")),
    CapabilityOwner("news_agent", "News Agent", "ai", 2, ("news_collection", "source_confirmation", "news_quality")),
    CapabilityOwner("risk_engine", "Risk Engine", "engine", 4, ("risk_limits", "dangerous_action_block", "drawdown_control")),
    CapabilityOwner("portfolio_engine", "Portfolio Engine", "engine", 4, ("portfolio_value", "position_exposure", "capital_accounting")),
    CapabilityOwner("paper_trading_bot", "Paper Trading Bot", "ai", 4, ("paper_execution", "position_lifecycle", "demo_trading")),
    CapabilityOwner("confidence_engine", "Confidence Engine", "engine", 1, ("confidence_calibration",)),
    CapabilityOwner("consensus_engine", "Consensus Engine", "engine", 1, ("agent_disagreement", "consensus_calculation")),
    CapabilityOwner("stress_bot", "Stress Bot", "ai", 4, ("stress_scenarios", "risk_overload_test")),
    CapabilityOwner("learning_engine", "Learning Engine", "ai", 1, ("mistake_learning", "rule_validation", "improvement_feedback")),
    CapabilityOwner("security_guard", "Security Guard", "guard", 1, ("real_order_block", "security_policy", "access_protection")),
)


def capability_registry() -> tuple[CapabilityOwner, ...]:
    specialized = tuple(
        CapabilityOwner(
            spec.id,
            spec.name,
            "specialized_news_ai",
            _priority_for_news_agent(spec.id),
            (f"news_domain:{spec.id}",),
            ("specialized_news", *spec.categories, *spec.source_ids),
        )
        for spec in NEWS_AGENTS
    )
    return CORE_OWNERS + specialized


def architecture_audit() -> dict[str, Any]:
    owners = capability_registry()
    registered_ids = {owner.component_id for owner in owners}
    learning_missing = sorted(BOT_NAMES - registered_ids)
    harmful = _duplicate_capabilities(owners)
    priorities = {
        priority: sorted(owner.component_id for owner in owners if owner.priority == priority)
        for priority in range(1, 5)
    }
    return {
        "status": "ok" if not learning_missing and not harmful else "warning",
        "component_count": len(owners),
        "core_component_count": len(CORE_OWNERS),
        "specialized_news_ai_count": len(NEWS_AGENTS),
        "learning_registry_missing": learning_missing,
        "harmful_duplicates": harmful,
        "priorities": priorities,
        "policy": "Extend an existing owner before creating another AI with the same capability.",
    }


def owner_for(capability: str) -> list[str]:
    normalized = _normalize(capability)
    return [
        owner.component_id
        for owner in capability_registry()
        if normalized in {_normalize(item) for item in (*owner.capabilities, *owner.shared_tags)}
    ]


def _duplicate_capabilities(owners: Iterable[CapabilityOwner]) -> list[dict[str, Any]]:
    index: dict[str, list[str]] = {}
    for owner in owners:
        for capability in owner.capabilities:
            index.setdefault(_normalize(capability), []).append(owner.component_id)
    return [
        {"capability": capability, "owners": sorted(component_ids)}
        for capability, component_ids in sorted(index.items())
        if len(component_ids) > 1
    ]


def _priority_for_news_agent(agent_id: str) -> int:
    if agent_id in {"economy_ai", "finance_ai", "politics_ai", "world_ai"}:
        return 2
    if agent_id in {"crypto_ai", "security_ai"}:
        return 3
    return 2


def _normalize(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")
