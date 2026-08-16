"""End-to-end shadow record contract for Architecture V2.

The helpers in this module are deliberately non-executing. They turn the exact
canonical paper evidence packet plus a :class:`RuntimeShadowV2` result into a
persistable/auditable record, and later attach the observed paper settlement.
Nothing in this module can grant paper or live execution authority.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from typing import Any, Mapping, Sequence

from .general_controller_v2 import GateSignal
from .runtime_shadow_integration_v2 import RuntimeShadowResult, immutable_shadow_input


SHADOW_RECORD_VERSION = 1
LEARNING_PROMOTION_PATH = (
    "candidate",
    "replay_validated",
    "shadow_validated",
    "active",
)


def build_runtime_shadow_record(
    *,
    decision_id: str,
    symbol: str,
    decision_ts_ms: int,
    evidence_packet: Any,
    gates: Sequence[GateSignal],
    result: RuntimeShadowResult,
) -> dict[str, Any]:
    """Build the immutable-at-decision portion of the V2 runtime audit record."""

    clean_decision_id = str(decision_id or "").strip()
    if not clean_decision_id:
        raise ValueError("decision_id must not be empty")
    if int(decision_ts_ms) <= 0:
        raise ValueError("decision_ts_ms must be positive")

    shadow_input = immutable_shadow_input(evidence_packet)
    if result.snapshot_id != shadow_input.snapshot_id or result.evidence_hash != shadow_input.evidence_hash:
        raise ValueError("shadow result lineage does not match canonical evidence packet")
    if result.execution_authority or result.controller.execution_authority:
        raise ValueError("V2 shadow runtime cannot have execution authority")
    if result.comparison.challenger.execution_authority:
        raise ValueError("V2 challenger cannot have execution authority")

    evidence_max_ts_ms = max(
        int(getattr(evidence_packet, "market_timestamp_ms", 0) or 0),
        int(getattr(evidence_packet, "received_timestamp_ms", 0) or 0),
    )
    if evidence_max_ts_ms <= 0:
        raise ValueError("evidence timestamp must be positive")
    if evidence_max_ts_ms > int(decision_ts_ms):
        raise ValueError("look-ahead evidence is forbidden")

    gate_rows = []
    for gate in gates:
        gate_rows.append(
            {
                "gate": gate.gate,
                "verdict": gate.verdict.value,
                "reasons": list(gate.reasons),
                "max_notional_usdt": gate.max_notional_usdt,
            }
        )

    return {
        "schema_version": SHADOW_RECORD_VERSION,
        "decision_id": clean_decision_id,
        "symbol": str(symbol or "").strip().upper(),
        "snapshot_id": result.snapshot_id,
        "evidence_hash": result.evidence_hash,
        "decision_ts_ms": int(decision_ts_ms),
        "evidence_max_ts_ms": evidence_max_ts_ms,
        "champion_action": result.comparison.authoritative.decision.value,
        "challenger_action": result.comparison.challenger.decision.value,
        "decision_match": bool(result.comparison.decision_match),
        "same_evidence": bool(result.comparison.same_evidence),
        "controller": result.controller.to_dict(),
        "gates": gate_rows,
        "execution_authority": False,
        "paper_authority_switched": False,
        "settlement": None,
        "learning_candidate": None,
    }


def idempotent_upsert_record(
    records: Mapping[str, Any] | None,
    record: Mapping[str, Any],
    *,
    max_records: int = 500,
) -> tuple[dict[str, Any], bool]:
    """Insert one decision once; identical retries are no-ops, conflicts fail closed."""

    if max_records < 1:
        raise ValueError("max_records must be positive")
    result = dict(records or {})
    decision_id = str(record.get("decision_id") or "").strip()
    if not decision_id:
        raise ValueError("record decision_id must not be empty")

    previous = result.get(decision_id)
    if previous is not None:
        if not isinstance(previous, Mapping):
            raise ValueError("persisted shadow record is invalid")
        if (
            str(previous.get("snapshot_id") or "") != str(record.get("snapshot_id") or "")
            or str(previous.get("evidence_hash") or "") != str(record.get("evidence_hash") or "")
        ):
            raise ValueError("decision_id already exists with different immutable lineage")
        return result, False

    result[decision_id] = deepcopy(dict(record))
    if len(result) > max_records:
        ordered = sorted(
            result.items(),
            key=lambda item: int(item[1].get("decision_ts_ms", 0) or 0)
            if isinstance(item[1], Mapping)
            else 0,
            reverse=True,
        )[:max_records]
        result = dict(ordered)
    return result, True


def attach_paper_settlement(
    record: Mapping[str, Any],
    *,
    settled_at_ms: int,
    side: str,
    quantity: float,
    entry_price: float,
    exit_price: float,
    entry_fee: float,
    exit_fee: float,
    net_pnl: float,
    slippage_cost: float = 0.0,
) -> dict[str, Any]:
    """Attach observed champion settlement and a replay-ready, no-look-ahead row."""

    if int(settled_at_ms) <= 0:
        raise ValueError("settled_at_ms must be positive")
    decision_ts_ms = int(record.get("decision_ts_ms", 0) or 0)
    evidence_max_ts_ms = int(record.get("evidence_max_ts_ms", 0) or 0)
    if decision_ts_ms <= 0 or evidence_max_ts_ms <= 0 or evidence_max_ts_ms > decision_ts_ms:
        raise ValueError("record contains invalid replay chronology")
    if int(settled_at_ms) < decision_ts_ms:
        raise ValueError("settlement cannot predate the decision")

    qty = float(quantity)
    entry = float(entry_price)
    exit_value = float(exit_price)
    entry_fee_value = float(entry_fee)
    exit_fee_value = float(exit_fee)
    slippage_value = float(slippage_cost)
    if qty <= 0 or entry <= 0 or exit_value <= 0:
        raise ValueError("paper settlement quantity/prices must be positive")
    if entry_fee_value < 0 or exit_fee_value < 0 or slippage_value < 0:
        raise ValueError("paper settlement costs must be non-negative")

    net = float(net_pnl)
    total_fees = entry_fee_value + exit_fee_value
    gross_pnl = net + total_fees + slippage_value
    turnover = qty * entry + qty * exit_value

    result = deepcopy(dict(record))
    result["settlement"] = {
        "settled_at_ms": int(settled_at_ms),
        "side": str(side).strip().upper(),
        "quantity": qty,
        "entry_price": entry,
        "exit_price": exit_value,
        "entry_fee": entry_fee_value,
        "exit_fee": exit_fee_value,
        "fees": total_fees,
        "slippage_cost": slippage_value,
        "gross_pnl": gross_pnl,
        "net_pnl": net,
        "turnover": turnover,
        "replay_champion": {
            "path": "champion",
            "snapshot_id": str(record.get("snapshot_id") or ""),
            "evidence_hash": str(record.get("evidence_hash") or ""),
            "decision_ts_ms": decision_ts_ms,
            "evidence_max_ts_ms": evidence_max_ts_ms,
            "gross_pnl": gross_pnl,
            "fees": total_fees,
            "slippage_cost": slippage_value,
            "turnover": turnover,
            "execution_authority": False,
        },
        "challenger_action": str(record.get("challenger_action") or "WAIT"),
        "counterfactual_outcome_pending_replay": True,
    }
    result["learning_candidate"] = {
        "stage": "candidate",
        "promotion_path": list(LEARNING_PROMOTION_PATH),
        "decision_id": str(record.get("decision_id") or ""),
        "snapshot_id": str(record.get("snapshot_id") or ""),
        "evidence_hash": str(record.get("evidence_hash") or ""),
        "observed_net_pnl": net,
        "execution_authority": False,
        "direct_activation_allowed": False,
    }
    result["execution_authority"] = False
    result["paper_authority_switched"] = False
    return result


__all__ = [
    "LEARNING_PROMOTION_PATH",
    "SHADOW_RECORD_VERSION",
    "attach_paper_settlement",
    "build_runtime_shadow_record",
    "idempotent_upsert_record",
]
