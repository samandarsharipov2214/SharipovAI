"""Canonical fail-closed gate adapter for Architecture V2 paper decisions.

The adapter translates already-persisted canonical paper evidence into the
mandatory General Controller V2 Risk / Portfolio / Security gates. It never
creates trading direction and never grants execution authority.
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from trading_candidate import TradingEnvironment

from .general_controller_v2 import GateSignal, GateVerdict


class CanonicalShadowGateProvider:
    """Build mandatory V2 gates from canonical paper decision evidence."""

    def __init__(self, database: Any) -> None:
        if database is None or not callable(getattr(database, "get_json", None)):
            raise ValueError("canonical V2 gates require a project database")
        self.database = database

    def pre_decision(self, packet: Any) -> tuple[GateSignal, ...]:
        """Evaluate gates before GC V2 chooses direction.

        Security at this stage proves only that the candidate is PAPER-only and
        carries no live approval identity. Structural TradingCandidate validation
        remains mandatory after the controller decision and may still downgrade
        the result fail-closed.
        """

        decision_id = str(getattr(packet, "candidate_id", "") or "").strip()
        if not decision_id:
            return self._all_wait("missing decision/evidence identity")
        return (
            self._risk_gate(decision_id, packet),
            self._portfolio_gate(decision_id, packet),
            self._security_gate(None, packet),
        )

    def __call__(self, authorization: Any, packet: Any, state: Mapping[str, Any]) -> tuple[GateSignal, ...]:
        del state  # Portfolio evidence is the immutable snapshot captured for this decision.
        decision_id = str(getattr(authorization, "decision_id", "") or "").strip()
        if not decision_id or str(getattr(packet, "candidate_id", "") or "").strip() != decision_id:
            return self._all_wait("decision/evidence identity mismatch")

        return (
            self._risk_gate(decision_id, packet),
            self._portfolio_gate(decision_id, packet),
            self._security_gate(authorization, packet),
        )

    def _risk_gate(self, decision_id: str, packet: Any) -> GateSignal:
        packet_blocks = tuple(str(item) for item in getattr(packet, "risk_blocks", ()) if str(item).strip())
        if packet_blocks:
            return GateSignal("risk_engine", GateVerdict.BLOCK, reasons=packet_blocks)

        record = self.database.get_json("risk_assessments", f"risk-{decision_id}")
        value = _record_value(record)
        if value is None:
            return GateSignal("risk_engine", GateVerdict.WAIT, reasons=("missing canonical risk assessment",))
        if str(value.get("decision_id") or "") != decision_id:
            return GateSignal("risk_engine", GateVerdict.WAIT, reasons=("canonical risk lineage mismatch",))

        stored_score = _finite_or_none(value.get("risk_score"))
        packet_score = _finite_or_none(getattr(packet, "risk_score", None))
        if stored_score is None or packet_score is None or abs(stored_score - packet_score) > 1e-9:
            return GateSignal("risk_engine", GateVerdict.WAIT, reasons=("canonical risk score mismatch",))

        assessment = value.get("assessment") if isinstance(value.get("assessment"), Mapping) else {}
        blockers = tuple(str(item) for item in value.get("blocks", ()) if str(item).strip())
        assessment_blockers = tuple(str(item) for item in assessment.get("blockers", ()) if str(item).strip())
        hard_blocks = tuple(str(item) for item in assessment.get("hard_blocks", ()) if str(item).strip())
        reasons = tuple(dict.fromkeys(blockers + assessment_blockers + hard_blocks))
        if reasons:
            return GateSignal("risk_engine", GateVerdict.BLOCK, reasons=reasons)
        if assessment.get("allowed_virtual") is not True:
            return GateSignal(
                "risk_engine",
                GateVerdict.WAIT,
                reasons=("canonical risk assessment does not explicitly allow virtual execution",),
            )
        return GateSignal(
            "risk_engine",
            GateVerdict.PASS,
            reasons=(f"canonical risk evidence risk-{decision_id}",),
        )

    def _portfolio_gate(self, decision_id: str, packet: Any) -> GateSignal:
        snapshot_id = str(getattr(packet, "portfolio_snapshot_id", "") or "").strip()
        if not snapshot_id:
            return GateSignal("portfolio_engine", GateVerdict.WAIT, reasons=("missing portfolio snapshot id",))
        record = self.database.get_json("portfolio_snapshots", snapshot_id)
        value = _record_value(record)
        if value is None:
            return GateSignal("portfolio_engine", GateVerdict.WAIT, reasons=("missing canonical portfolio snapshot",))
        if str(value.get("decision_id") or "") != decision_id:
            return GateSignal("portfolio_engine", GateVerdict.WAIT, reasons=("canonical portfolio lineage mismatch",))
        if str(value.get("environment") or "").lower() != "paper":
            return GateSignal("portfolio_engine", GateVerdict.BLOCK, reasons=("portfolio snapshot is not paper-only",))

        cash = _finite_or_none(value.get("cash"))
        equity = _finite_or_none(value.get("equity"))
        if cash is None or equity is None:
            return GateSignal("portfolio_engine", GateVerdict.WAIT, reasons=("portfolio snapshot is incomplete",))
        if cash <= 0.0 or equity <= 0.0:
            return GateSignal(
                "portfolio_engine",
                GateVerdict.BLOCK,
                reasons=("paper portfolio has no positive deployable value",),
                max_notional_usdt=0.0,
            )

        # Hard solvency ceiling only. Portfolio cannot create BUY/SELL direction.
        max_notional = min(cash, equity)
        return GateSignal(
            "portfolio_engine",
            GateVerdict.PASS,
            reasons=(f"canonical portfolio snapshot {snapshot_id}",),
            max_notional_usdt=max_notional,
        )

    def _security_gate(self, authorization: Any | None, packet: Any) -> GateSignal:
        environment = getattr(packet, "environment", None)
        if environment is not TradingEnvironment.PAPER:
            return GateSignal(
                "security_guard",
                GateVerdict.BLOCK,
                reasons=("V2 paper gate provider is restricted to PAPER environment",),
            )
        if str(getattr(packet, "security_approval_id", "") or "").strip():
            return GateSignal(
                "security_guard",
                GateVerdict.BLOCK,
                reasons=("PAPER candidate must not carry a live security approval identity",),
            )

        if authorization is None:
            return GateSignal(
                "security_guard",
                GateVerdict.PASS,
                reasons=("PAPER-only pre-decision boundary; structural validation still required",),
            )

        candidate_result = getattr(authorization, "candidate_result", None)
        validation = getattr(candidate_result, "validation", None)
        if validation is None:
            return GateSignal("security_guard", GateVerdict.WAIT, reasons=("missing canonical candidate validation",))
        errors = tuple(str(item) for item in getattr(validation, "errors", ()) if str(item).strip())
        if getattr(validation, "valid", False) is not True:
            return GateSignal(
                "security_guard",
                GateVerdict.BLOCK,
                reasons=errors or ("canonical paper candidate validation failed",),
            )

        return GateSignal(
            "security_guard",
            GateVerdict.PASS,
            reasons=("canonical PAPER candidate validation passed; no live execution authority",),
        )

    @staticmethod
    def _all_wait(reason: str) -> tuple[GateSignal, ...]:
        return tuple(
            GateSignal(name, GateVerdict.WAIT, reasons=(reason,))
            for name in ("risk_engine", "portfolio_engine", "security_guard")
        )


def _record_value(record: Any) -> Mapping[str, Any] | None:
    if not isinstance(record, Mapping):
        return None
    value = record.get("value")
    return value if isinstance(value, Mapping) else None


def _finite_or_none(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


__all__ = ["CanonicalShadowGateProvider"]
