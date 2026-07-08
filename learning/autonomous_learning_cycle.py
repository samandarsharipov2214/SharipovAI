"""Autonomous paper-realism learning cycle for SharipovAI.

This module does not place real orders. It trains the system in a serious
paper-realism loop: decide, record evidence, simulate outcome, learn from the
result, and produce an honest morning report.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any

from learning.evidence_vault import EvidenceVault
from sharipovai_constitution import constitution_snapshot, now_iso


@dataclass(frozen=True)
class PaperScenario:
    symbol: str
    setup: str
    expected_edge: float
    risk_level: str
    blocker: str | None = None


SCENARIOS: tuple[PaperScenario, ...] = (
    PaperScenario("BTC/USDT", "mixed_market_breakout_watch", 0.18, "LOW", "news_confirmation_missing"),
    PaperScenario("ETH/USDT", "volume_confirmation_retest", -0.08, "MEDIUM", "early_entry_risk"),
    PaperScenario("SOL/USDT", "small_size_momentum_probe", 0.31, "MEDIUM", None),
    PaperScenario("BTC/USDT", "fee_drag_check", 0.06, "LOW", "commission_drag"),
)


def run_autonomous_learning_cycle(*, cycles: int = 4, vault: EvidenceVault | None = None) -> dict[str, Any]:
    """Run one safe learning cycle and return a report.

    The cycle behaves as if capital matters, while keeping LIVE trading blocked.
    Each scenario is recorded in Evidence Vault with evidence and a simulated
    outcome, so Learning/Evidence can replay why a decision happened.
    """

    started_at = now_iso()
    vault = vault or EvidenceVault()
    selected = list(SCENARIOS[: max(1, min(int(cycles), len(SCENARIOS)))])
    decisions: list[dict[str, Any]] = []
    lessons: list[dict[str, Any]] = []
    paper_pnl = 0.0
    fees = 0.0
    prevented_loss = 0.0

    for index, scenario in enumerate(selected, start=1):
        decision = _decide(scenario)
        fee = _fee_for(scenario, index)
        outcome = _paper_outcome(scenario, decision, fee)
        paper_pnl += outcome["net_pnl"]
        fees += fee
        prevented_loss += outcome.get("prevented_loss", 0.0)
        evidence = _evidence_for(scenario, decision, index)
        record = vault.record_decision(
            actor="autonomous_learning_cycle",
            decision=decision,
            topic=f"paper_realism:{scenario.symbol}:{scenario.setup}",
            confidence=outcome["confidence"],
            risk_level=scenario.risk_level,
            reason=outcome["reason"],
            evidence=evidence,
            policy_status="live_blocked_paper_realism",
            metadata={
                "symbol": scenario.symbol,
                "setup": scenario.setup,
                "capital_mode": "paper_realism",
                "real_money_protected": True,
                "carelessness_allowed": False,
                "cycle_index": index,
            },
        )
        vault.add_outcome(
            decision_id=str(record["decision_id"]),
            outcome="paper_profit" if outcome["net_pnl"] > 0 else "paper_loss" if outcome["net_pnl"] < 0 else "blocked_no_trade",
            impact_score=outcome["net_pnl"],
            notes=outcome["lesson"],
            learning_signal="positive" if outcome["net_pnl"] >= 0 else "negative",
        )
        decisions.append({"decision_id": record["decision_id"], **outcome, "evidence_count": len(evidence)})
        lessons.append(_lesson_for(scenario, decision, outcome))

    report = {
        "status": "ok",
        "started_at": started_at,
        "finished_at": now_iso(),
        "capital_mode": "paper_realism",
        "constitution": constitution_snapshot(),
        "summary": {
            "cycles": len(selected),
            "paper_pnl": round(paper_pnl, 2),
            "fees": round(fees, 2),
            "net_after_fees": round(paper_pnl, 2),
            "prevented_loss": round(prevented_loss, 2),
            "live_orders_blocked": True,
            "real_money_protected": True,
            "carelessness_allowed": False,
        },
        "decisions": decisions,
        "lessons": lessons,
        "next_actions": _next_actions(lessons, paper_pnl, prevented_loss),
    }
    return report


def morning_report() -> dict[str, Any]:
    """Run a compact learning cycle intended for the morning check-in."""

    report = run_autonomous_learning_cycle(cycles=4)
    summary = report["summary"]
    report["human_summary"] = (
        f"SharipovAI провёл {summary['cycles']} paper-realism проверок. "
        f"Paper PnL: {summary['paper_pnl']} USDT, комиссии: {summary['fees']} USDT, "
        f"предотвращённый риск: {summary['prevented_loss']} USDT. LIVE не трогал."
    )
    return report


def _decide(scenario: PaperScenario) -> str:
    if scenario.blocker in {"news_confirmation_missing", "early_entry_risk"}:
        return "WATCH"
    if scenario.expected_edge >= 0.25:
        return "PAPER_BUY_SMALL"
    return "WATCH"


def _fee_for(scenario: PaperScenario, index: int) -> float:
    base = 1.75 + index * 0.42
    if "BTC" in scenario.symbol:
        base += 0.65
    return round(base, 2)


def _paper_outcome(scenario: PaperScenario, decision: str, fee: float) -> dict[str, Any]:
    confidence = _confidence(scenario)
    if decision == "WATCH":
        avoided = abs(scenario.expected_edge) * 100 if scenario.expected_edge < 0 else max(0.0, 8.0 - scenario.expected_edge * 10)
        return {
            "symbol": scenario.symbol,
            "setup": scenario.setup,
            "decision": decision,
            "confidence": confidence,
            "gross_pnl": 0.0,
            "fee": 0.0,
            "net_pnl": 0.0,
            "prevented_loss": round(avoided, 2),
            "reason": f"WAIT/BLOCK выбран из-за {scenario.blocker or 'недостаточного преимущества'}.",
            "lesson": "Не входить без доказательств; отсутствие сделки тоже решение, если риск/доказательства слабые.",
        }
    gross = scenario.expected_edge * 100
    net = gross - fee
    return {
        "symbol": scenario.symbol,
        "setup": scenario.setup,
        "decision": decision,
        "confidence": confidence,
        "gross_pnl": round(gross, 2),
        "fee": fee,
        "net_pnl": round(net, 2),
        "prevented_loss": 0.0,
        "reason": "Малый paper-вход разрешён: риск ограничен, преимущество выше комиссии, LIVE заблокирован.",
        "lesson": "Даже прибыльная paper-сделка должна пройти проверку комиссий, размера и подтверждения.",
    }


def _confidence(scenario: PaperScenario) -> float:
    raw = 60.0 + scenario.expected_edge * 100
    if scenario.blocker:
        raw -= 12.0
    if scenario.risk_level == "LOW":
        raw += 4.0
    return round(max(5.0, min(97.0, raw)), 2)


def _evidence_for(scenario: PaperScenario, decision: str, index: int) -> list[dict[str, Any]]:
    checked_at = int(time.time())
    return [
        {
            "title": f"Scenario {index}: {scenario.symbol} {scenario.setup}",
            "source_domain": "sharipovai.local",
            "source_type": "paper_realism_scenario",
            "url": "",
            "trust_score": 72.0,
            "summary": f"Decision={decision}; blocker={scenario.blocker or 'none'}; risk={scenario.risk_level}.",
            "checked_at": checked_at,
        },
        {
            "title": "SharipovAI Constitution",
            "source_domain": "constitution.sharipovai.local",
            "source_type": "policy",
            "url": "",
            "trust_score": 95.0,
            "summary": "Demo protects real funds, but AI must train as if capital is real.",
            "checked_at": checked_at,
        },
    ]


def _lesson_for(scenario: PaperScenario, decision: str, outcome: dict[str, Any]) -> dict[str, Any]:
    if decision == "WATCH":
        return {
            "type": "risk_block",
            "symbol": scenario.symbol,
            "rule": "WAIT is a valid profit-protection action when evidence is weak.",
            "impact": outcome.get("prevented_loss", 0.0),
        }
    return {
        "type": "execution_quality",
        "symbol": scenario.symbol,
        "rule": "Small paper entries must beat fees and preserve downside discipline.",
        "impact": outcome.get("net_pnl", 0.0),
    }


def _next_actions(lessons: list[dict[str, Any]], paper_pnl: float, prevented_loss: float) -> list[str]:
    actions = [
        "Keep LIVE orders blocked until read-only exchange sync and manual approval are ready.",
        "Promote every paper loss/blocker into Learning/Evidence instead of hiding it.",
        "Show morning report in Telegram/Mini App with paper PnL, fees, prevented loss, and lessons.",
    ]
    if prevented_loss > abs(paper_pnl):
        actions.append("Treat avoided losses as a first-class win: capital protection is profit protection.")
    if any(lesson.get("type") == "execution_quality" for lesson in lessons):
        actions.append("Expand paper execution quality scoring: slippage, spread, fee drag, and confidence decay.")
    return actions
