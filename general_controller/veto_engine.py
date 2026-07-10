from __future__ import annotations

from collections.abc import Iterable

from .models import AgentReport

HARD_VETO_AGENTS = {"Security Guard", "Risk Engine"}


def detect_vetoes(reports: Iterable[AgentReport]) -> list[str]:
    vetoes: list[str] = []
    for report in reports:
        if report.agent in HARD_VETO_AGENTS and (
            report.recommendation in {"BLOCK", "PAUSE_SYSTEM"} or report.blockers
        ):
            vetoes.append(f"veto:{report.agent}")
        if report.agent == "AI Doctor" and report.recommendation == "PAUSE_SYSTEM":
            vetoes.append("veto:AI Doctor")
    return vetoes


def detect_conflicts(reports: Iterable[AgentReport]) -> list[str]:
    directional = {report.recommendation for report in reports if report.recommendation in {"BUY", "SELL"}}
    blockers = any(report.recommendation in {"BLOCK", "PAUSE_SYSTEM"} for report in reports)
    conflicts: list[str] = []
    if len(directional) > 1:
        conflicts.append("direction_conflict")
    if directional and blockers:
        conflicts.append("action_block_conflict")
    return conflicts


def majority_recommendation(reports: Iterable[AgentReport]) -> str:
    counts: dict[str, int] = {}
    for report in reports:
        counts[report.recommendation] = counts.get(report.recommendation, 0) + 1
    if not counts:
        return "WAIT"
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
