"""Runtime adapter that observes the authoritative paper path with GC V2.

The challenger consumes the same immutable evidence packet as the canonical
paper runtime, but its directional quality is computed independently from the
legacy consensus path. Risk/Portfolio/Security remain explicit non-directional
gates and the challenger never has execution authority.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Mapping, Sequence

from trading_candidate import TradingDecision, TradingSide

from .canonical_runtime import PaperDecisionAuthorization
from .general_controller_v2 import GateSignal, GeneralControllerDecision, GeneralControllerV2
from .runtime_decision_v2 import evaluate_controller_v2
from .shadow_dual_run_v2 import (
    Decision,
    PathDecision,
    ShadowComparison,
    ShadowInput,
    compare_shadow,
)


@dataclass(frozen=True, slots=True)
class RuntimeShadowResult:
    comparison: ShadowComparison
    controller: GeneralControllerDecision
    snapshot_id: str
    evidence_hash: str
    execution_authority: bool = False


class RuntimeShadowV2:
    """Evaluate independent GC V2 beside the current paper authorization."""

    def __init__(self, controller: GeneralControllerV2 | None = None) -> None:
        self.controller = controller or GeneralControllerV2()

    def evaluate(
        self,
        *,
        authorization: PaperDecisionAuthorization,
        evidence_packet: Any,
        agent_payloads: Sequence[Mapping[str, Any]],
        gates: Sequence[GateSignal],
    ) -> RuntimeShadowResult:
        candidate = authorization.candidate_result.candidate
        if candidate.candidate_id != authorization.decision_id:
            raise ValueError("paper authorization candidate identity mismatch")
        if getattr(evidence_packet, "candidate_id", None) != authorization.decision_id:
            raise ValueError("shadow evidence packet must match authoritative decision_id")
        if getattr(evidence_packet, "market_timestamp_ms", None) != candidate.market_timestamp_ms:
            raise ValueError("shadow and authoritative paths must use the same market timestamp")

        shadow_input = immutable_shadow_input(evidence_packet)
        validation = authorization.candidate_result.validation
        freshness_errors = _freshness_errors(getattr(validation, "errors", ()))
        evaluated = evaluate_controller_v2(
            agent_payloads,
            gates=gates,
            freshness_errors=freshness_errors,
            controller=self.controller,
        )
        controller = evaluated.controller

        authoritative = PathDecision(
            path="canonical_paper_runtime",
            decision=_authoritative_direction(authorization),
            reason=authorization.reason,
            snapshot_id=shadow_input.snapshot_id,
            evidence_hash=shadow_input.evidence_hash,
            execution_authority=True,
        )
        challenger = PathDecision(
            path="general_controller_v2_shadow",
            decision=Decision(controller.final_intent.value),
            reason=controller.reason,
            snapshot_id=shadow_input.snapshot_id,
            evidence_hash=shadow_input.evidence_hash,
            execution_authority=False,
        )
        comparison = compare_shadow(
            shadow_input=shadow_input,
            authoritative=authoritative,
            challenger=challenger,
        )
        return RuntimeShadowResult(
            comparison=comparison,
            controller=controller,
            snapshot_id=shadow_input.snapshot_id,
            evidence_hash=shadow_input.evidence_hash,
            execution_authority=False,
        )


def immutable_shadow_input(evidence_packet: Any) -> ShadowInput:
    """Fingerprint the exact canonical evidence packet consumed by both paths."""

    candidate_id = str(getattr(evidence_packet, "candidate_id", "") or "").strip()
    market_ts_ms = int(getattr(evidence_packet, "market_timestamp_ms", 0) or 0)
    if not candidate_id or market_ts_ms <= 0:
        raise ValueError("canonical evidence packet lacks immutable identity")
    payload = _jsonable(asdict(evidence_packet))
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    evidence_hash = hashlib.sha256(encoded).hexdigest()
    return ShadowInput(
        snapshot_id=f"{candidate_id}:{market_ts_ms}",
        evidence_hash=evidence_hash,
        market_ts_ms=market_ts_ms,
    )


def _authoritative_direction(authorization: PaperDecisionAuthorization) -> Decision:
    if not authorization.authorized or authorization.decision is not TradingDecision.ALLOW:
        return Decision.WAIT
    side = authorization.candidate_result.candidate.side
    if side is TradingSide.BUY:
        return Decision.BUY
    if side is TradingSide.SELL:
        return Decision.SELL
    return Decision.WAIT


def _freshness_errors(errors: Any) -> tuple[str, ...]:
    freshness_markers = (
        "candidate is expired",
        "market data is stale",
        "market_timestamp_ms is too far in the future",
        "received_timestamp_ms is too far in the future",
    )
    rows = tuple(str(item) for item in (errors or ()) if str(item).strip())
    return tuple(item for item in rows if any(marker in item for marker in freshness_markers))


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


__all__ = ["RuntimeShadowResult", "RuntimeShadowV2", "immutable_shadow_input"]
