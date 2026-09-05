"""Council-authorized autonomous paper loop.

New entries are impossible without a canonical Decision Quality assessment and a
validated TradingCandidate. Protective exits remain local and immediate because
capital preservation must not wait for a new council round.
"""
from __future__ import annotations

import copy
import hashlib
import math
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from threading import Thread
from typing import Any, Callable, Mapping, Sequence

from decision_quality import CandidateEvidencePacket
from exchange_connector.bybit_instrument_rules import BybitInstrumentRulesService
from trading_core.costs import ExecutionCostModel
from trading_core.models import MarketEvent, Side
from trading_candidate import TradingDecision

from .canonical_runtime import CanonicalPaperDecisionRuntime, PaperDecisionAuthorization
from .decision_trace import persist_decision_trace, read_decision_trace, read_decision_traces
from .general_controller_v2 import GateSignal
from .loop import AutonomousPaperLoop
from .runtime_e2e_shadow_v2 import (
    attach_paper_settlement,
    build_runtime_shadow_record,
    idempotent_upsert_record,
)
from .runtime_shadow_integration_v2 import RuntimeShadowV2
from .trade_identity import new_trade_id


@dataclass(frozen=True, slots=True)
class CouncilEntryProposal:
    decision_id: str
    agent_payloads: Sequence[Mapping[str, Any]]
    evidence_packet: CandidateEvidencePacket
    general_controller_decision: TradingDecision
    regime: str = "unknown"


ProposalProvider = Callable[[str, Any, Mapping[str, Any]], CouncilEntryProposal | None]
ShadowGateProvider = Callable[
    [PaperDecisionAuthorization, CandidateEvidencePacket, Mapping[str, Any]],
    Sequence[GateSignal],
]


class PaperExecutionRejected(RuntimeError):
    """A fail-closed rejection before a canonical PAPER state transition."""


class CouncilAuthorizedPaperLoop(AutonomousPaperLoop):
    """Autonomous paper loop whose new entries require council authorization."""

    # Expected edge / price move must cover this multiple of all-in round-trip cost.
    # This is a cost-coverage margin, not a time wait.
    ANTI_CHURN_COST_MARGIN = 1.5
    ANTI_CHURN_TURNOVER_WINDOW_MS = 15 * 60 * 1000
    ANTI_CHURN_MAX_ROUND_TRIPS = 3
    ANTI_CHURN_FEE_EQUITY_FRACTION = 0.005
    ANTI_CHURN_REENTRY = "anti_churn_reentry"
    ANTI_CHURN_COST_NOT_COVERED = "anti_churn_cost_not_covered"
    ANTI_CHURN_TURNOVER_LIMIT = "anti_churn_turnover_limit"

    def __init__(
        self,
        stream,
        *,
        decision_runtime: CanonicalPaperDecisionRuntime,
        proposal_provider: ProposalProvider,
        database=None,
        shadow_runtime: RuntimeShadowV2 | None = None,
        shadow_gate_provider: ShadowGateProvider | None = None,
        shadow_timeout_seconds: float = 0.05,
        instrument_rules: BybitInstrumentRulesService,
        cost_model: ExecutionCostModel | None = None,
    ) -> None:
        super().__init__(stream, database=database or decision_runtime.database)
        if decision_runtime.database.dsn != self.database.dsn:
            raise ValueError("paper loop and decision runtime must use the same database")
        if float(shadow_timeout_seconds) <= 0:
            raise ValueError("shadow_timeout_seconds must be positive")
        self.decision_runtime = decision_runtime
        self.proposal_provider = proposal_provider
        self.shadow_runtime = shadow_runtime or RuntimeShadowV2()
        # No gate is fabricated. Until the runtime supplies explicit Risk,
        # Portfolio and Security evidence, GeneralControllerV2 fails closed to WAIT.
        self.shadow_gate_provider = shadow_gate_provider or (lambda _auth, _packet, _state: ())
        self.shadow_timeout_seconds = float(shadow_timeout_seconds)
        self.instrument_rules = instrument_rules
        self.cost_model = cost_model or ExecutionCostModel(fee_rate=self.fee_rate)
        self._pending_authorization_evidence: dict[str, Any] | None = None
        self._pending_exit_context: dict[str, Any] | None = None
        self._pending_execution: dict[str, Any] | None = None
        self._state["peak_equity"] = max(
            float(self._state.get("peak_equity", 0.0) or 0.0),
            float(self._state.get("equity", 0.0) or 0.0),
        )
        if not isinstance(self._state.get("v2_shadow_records"), dict):
            self._state["v2_shadow_records"] = {}
        if not isinstance(self._state.get("v2_shadow_errors"), list):
            self._state["v2_shadow_errors"] = []
        if not isinstance(self._state.get("pending_authorized_executions"), dict):
            self._state["pending_authorized_executions"] = {}
        if not isinstance(self._state.get("pending_protective_executions"), dict):
            self._state["pending_protective_executions"] = {}
        if not isinstance(self._state.get("last_close_by_symbol"), dict):
            self._state["last_close_by_symbol"] = {}
        # A close is already an immutable PAPER fact when the process comes
        # back.  Recover only explicitly marked, previously failed settlement
        # writes; do not infer settlements from arbitrary historical trades.
        self._recover_pending_settlements()
        self._recover_pending_authorized_executions()
        self._recover_pending_protective_executions()

    def _trace(self, symbol: str, status: str, reason: str, **extra: Any) -> dict[str, Any]:
        return persist_decision_trace(
            self.database,
            symbol,
            {
                "status": status,
                "reason": reason,
                **extra,
            },
            now_ms=self._now_ms(),
        )

    def tick(self) -> None:
        with self._lock:
            self._recover_pending_authorized_executions()
            self._recover_pending_protective_executions()
        market = self.stream.snapshot()
        if not market.get("verified"):
            reason = "Market stream is unavailable or stale; no paper order created"
            for symbol in self.stream.symbols:
                self._trace(
                    symbol,
                    "BLOCK",
                    reason,
                    phase="market_stream",
                    market_verified=False,
                )
            self._event("BLOCK", reason)
            return

        with self._lock:
            for symbol in self.stream.symbols:
                try:
                    quote = self.stream.quote(symbol)
                except Exception as exc:
                    reason = f"verified_quote_error:{type(exc).__name__}: {exc}"
                    self._trace(symbol, "BLOCK", reason, phase="quote")
                    self._event("BLOCK", reason, symbol)
                    continue

                position = self._state["positions"].get(symbol)
                if position:
                    # Capital-preservation exits are intentionally local and
                    # immediate.  If none fires, keep the position available
                    # for a fresh, canonical GC V2 SELL decision below.
                    self._manage_protective_exit(symbol, quote)
                    position = self._state["positions"].get(symbol)
                    if position is None:
                        continue

                try:
                    proposal = self.proposal_provider(
                        symbol,
                        quote,
                        self._proposal_state_snapshot(),
                    )
                except Exception as exc:
                    reason = f"proposal_provider_error:{type(exc).__name__}: {exc}"
                    self._trace(symbol, "BLOCK", reason, phase="proposal_provider")
                    self._event("BLOCK", reason, symbol)
                    continue

                if proposal is None:
                    trace = read_decision_trace(self.database, symbol) or {}
                    reason = str(trace.get("reason") or "no fresh canonical council proposal")
                    action = "BLOCK" if str(trace.get("status") or "").upper() == "BLOCK" else "WAIT"
                    self._event(action, reason, symbol)
                    continue

                decision_ts_ms = self._now_ms()
                try:
                    authorization = self.decision_runtime.assess_entry(
                        proposal.decision_id,
                        proposal.agent_payloads,
                        proposal.evidence_packet,
                        general_controller_decision=proposal.general_controller_decision,
                        now_ms=decision_ts_ms,
                        regime=proposal.regime,
                    )
                except Exception as exc:
                    reason = f"canonical_decision_error:{type(exc).__name__}: {exc}"
                    self._trace(
                        symbol,
                        "BLOCK",
                        reason,
                        phase="decision_quality",
                        decision_id=proposal.decision_id,
                    )
                    self._event("BLOCK", reason, symbol)
                    continue

                # Architecture V2 observes the exact canonical decision path. This
                # call is bounded and exception-isolated: champion authorization is
                # never changed by shadow success, failure or timeout.
                self._evaluate_v2_shadow(
                    symbol=symbol,
                    proposal=proposal,
                    authorization=authorization,
                    decision_ts_ms=decision_ts_ms,
                )

                validation = authorization.candidate_result.validation
                assessment = authorization.assessment
                candidate_side = authorization.candidate_result.candidate.side.value.upper()
                decision_action = candidate_side if authorization.authorized else (
                    "BLOCK" if authorization.decision is TradingDecision.BLOCK else "WAIT"
                )
                self._trace(
                    symbol,
                    decision_action,
                    authorization.reason,
                    phase="decision_quality",
                    decision_id=authorization.decision_id,
                    decision_quality_action=assessment.action,
                    decision_quality_confidence=assessment.confidence,
                    decision_quality_agreement=assessment.agreement,
                    decision_quality_blocked=assessment.blocked,
                    candidate_validation_valid=validation.valid,
                    candidate_validation_errors=list(validation.errors),
                    final_decision=authorization.decision.value,
                    authorized=authorization.authorized,
                    v2_shadow_execution_authority=False,
                )

                if not authorization.authorized:
                    action = "BLOCK" if authorization.decision is TradingDecision.BLOCK else "WAIT"
                    self._event(action, authorization.reason, symbol)
                    continue

                if authorization.candidate_result.candidate.symbol != symbol:
                    reason = "authorized candidate symbol does not match loop symbol"
                    self._trace(symbol, "BLOCK", reason, phase="candidate_validation")
                    self._event("BLOCK", reason, symbol)
                    continue

                if position is not None and candidate_side == "SELL":
                    try:
                        prepared_exit = self._prepare_close(symbol, quote)
                    except Exception as exc:
                        reason = f"paper_execution_preflight_error:{type(exc).__name__}: {exc}"
                        self._trace(symbol, "BLOCK", reason, phase="virtual_execution")
                        self._event("BLOCK", reason, symbol)
                        continue
                    exit_reason = f"canonical_council_sell:{authorization.decision_id}"
                    self._stage_authorized_execution(
                        symbol=symbol,
                        side="SELL",
                        reason=exit_reason,
                        authorization=authorization,
                        execution=prepared_exit,
                    )
                    try:
                        self.decision_runtime.consume_authorization(
                            authorization,
                            consumed_at_ms=self._now_ms(),
                        )
                    except Exception as exc:
                        reason = f"authorization_consumption_error:{type(exc).__name__}: {exc}"
                        self._trace(symbol, "BLOCK", reason, phase="authorization_consumption")
                        self._event("BLOCK", reason, symbol)
                        continue

                    self._apply_authorized_execution(authorization.decision_id)
                    self._trace(
                        symbol,
                        "SELL",
                        f"canonical council authorization consumed and paper SELL closed long: {authorization.decision_id}",
                        phase="virtual_execution",
                        decision_id=authorization.decision_id,
                        authorized=True,
                    )
                    continue

                if position is not None:
                    reason = "spot paper loop already has a long position; BUY cannot increase exposure"
                    self._trace(symbol, "WAIT", reason, phase="execution_gate")
                    self._event("WAIT", reason, symbol)
                    continue

                if candidate_side != "BUY":
                    reason = "spot paper loop does not open a short position"
                    self._trace(symbol, "WAIT", reason, phase="execution_gate")
                    self._event("WAIT", reason, symbol)
                    continue

                anti_churn_reason = self._anti_churn_buy_block_reason(
                    symbol,
                    quote,
                    authorization,
                    proposal=proposal,
                )
                if anti_churn_reason:
                    action = (
                        "BLOCK"
                        if anti_churn_reason.startswith(self.ANTI_CHURN_TURNOVER_LIMIT)
                        else "WAIT"
                    )
                    self._trace(
                        symbol,
                        action,
                        anti_churn_reason,
                        phase="anti_churn",
                        decision_id=authorization.decision_id,
                        authorized=True,
                        anti_churn_blocked=True,
                    )
                    self._event(action, anti_churn_reason, symbol)
                    continue

                try:
                    prepared_entry = self._prepare_open(symbol, quote)
                except Exception as exc:
                    reason = f"paper_execution_preflight_error:{type(exc).__name__}: {exc}"
                    self._trace(symbol, "BLOCK", reason, phase="virtual_execution")
                    self._event("BLOCK", reason, symbol)
                    continue

                entry_reason = f"canonical_council_allow:{authorization.decision_id}"
                self._stage_authorized_execution(
                    symbol=symbol,
                    side="BUY",
                    reason=entry_reason,
                    authorization=authorization,
                    execution=prepared_entry,
                )
                try:
                    self.decision_runtime.consume_authorization(
                        authorization,
                        consumed_at_ms=self._now_ms(),
                    )
                except Exception as exc:
                    reason = f"authorization_consumption_error:{type(exc).__name__}: {exc}"
                    self._trace(symbol, "BLOCK", reason, phase="authorization_consumption")
                    self._event("BLOCK", reason, symbol)
                    continue

                self._apply_authorized_execution(authorization.decision_id)
                position = self._state["positions"].get(symbol)
                if position is None:
                    reason = "authorized entry could not allocate a safe paper budget"
                    self._trace(symbol, "BLOCK", reason, phase="virtual_execution")
                    self._event("BLOCK", reason, symbol)
                    continue
                self._trace(
                    symbol,
                    "BUY",
                    f"canonical council authorization consumed and paper BUY opened: {authorization.decision_id}",
                    phase="virtual_execution",
                    decision_id=authorization.decision_id,
                    authorized=True,
                )

            self._mark_to_market(market)
            self._state["peak_equity"] = max(
                float(self._state.get("peak_equity", 0.0) or 0.0),
                float(self._state.get("equity", 0.0) or 0.0),
            )
            self._persist()

    def _evaluate_v2_shadow(
        self,
        *,
        symbol: str,
        proposal: CouncilEntryProposal,
        authorization: PaperDecisionAuthorization,
        decision_ts_ms: int,
    ) -> None:
        holder: dict[str, Any] = {}
        state_snapshot = self._proposal_state_snapshot()

        def evaluate() -> None:
            try:
                gates = tuple(
                    self.shadow_gate_provider(
                        authorization,
                        proposal.evidence_packet,
                        state_snapshot,
                    )
                )
                result = self.shadow_runtime.evaluate(
                    authorization=authorization,
                    evidence_packet=proposal.evidence_packet,
                    agent_payloads=proposal.agent_payloads,
                    gates=gates,
                )
                holder["record"] = build_runtime_shadow_record(
                    decision_id=authorization.decision_id,
                    symbol=symbol,
                    decision_ts_ms=decision_ts_ms,
                    evidence_packet=proposal.evidence_packet,
                    gates=gates,
                    result=result,
                )
            except Exception as exc:  # shadow failures can never affect champion
                holder["error"] = f"{type(exc).__name__}: {exc}"

        worker = Thread(target=evaluate, name="gc-v2-shadow-eval", daemon=True)
        worker.start()
        worker.join(self.shadow_timeout_seconds)
        if worker.is_alive():
            self._record_v2_shadow_error(
                authorization.decision_id,
                symbol,
                "TimeoutError: GC V2 shadow evaluation exceeded bounded timeout",
            )
            return
        if "error" in holder:
            self._record_v2_shadow_error(
                authorization.decision_id,
                symbol,
                str(holder["error"]),
            )
            return

        record = holder.get("record")
        if not isinstance(record, Mapping):
            self._record_v2_shadow_error(
                authorization.decision_id,
                symbol,
                "RuntimeError: GC V2 shadow evaluation returned no auditable record",
            )
            return
        try:
            records, inserted = idempotent_upsert_record(
                self._state.get("v2_shadow_records"),
                record,
            )
            self._state["v2_shadow_records"] = records
            if inserted:
                self._trace(
                    symbol,
                    "OBSERVE",
                    "GC V2 shadow decision recorded; paper champion authority unchanged",
                    phase="v2_shadow",
                    decision_id=authorization.decision_id,
                    snapshot_id=record.get("snapshot_id"),
                    evidence_hash=record.get("evidence_hash"),
                    champion_action=record.get("champion_action"),
                    challenger_action=record.get("challenger_action"),
                    execution_authority=False,
                )
        except Exception as exc:
            self._record_v2_shadow_error(
                authorization.decision_id,
                symbol,
                f"{type(exc).__name__}: {exc}",
            )

    def _record_v2_shadow_error(self, decision_id: str, symbol: str, error: str) -> None:
        errors = self._state.setdefault("v2_shadow_errors", [])
        if not isinstance(errors, list):
            errors = []
            self._state["v2_shadow_errors"] = errors
        row = {
            "decision_id": str(decision_id),
            "symbol": str(symbol).upper(),
            "created_at_ms": self._now_ms(),
            "error": str(error),
            "execution_authority": False,
        }
        if not errors or errors[-1].get("decision_id") != row["decision_id"] or errors[-1].get("error") != row["error"]:
            errors.append(row)
            del errors[:-100]
        self._trace(
            symbol,
            "OBSERVE",
            f"GC V2 shadow unavailable; champion path unaffected: {error}",
            phase="v2_shadow",
            decision_id=decision_id,
            execution_authority=False,
        )

    def _manage_protective_exit(self, symbol: str, quote: Any) -> None:
        """Execute only position-relative emergency exits without a new Council vote.

        Bybit's rolling 24h percentage is market context, not a loss/profit
        measurement for this position.  A non-emergency momentum SELL therefore
        continues through the canonical proposal and authorization path below.
        """

        position = self._state["positions"].get(symbol)
        if not position:
            return
        entry = float(position["entry_price"])
        move = (float(quote.price) - entry) / entry * 100
        reason = None
        if move <= -self.stop_loss_percent:
            reason = "protective_stop_loss"
        elif move >= self.take_profit_percent:
            reason = "protective_take_profit"
        if reason is None:
            return
        state_before = copy.deepcopy(self._state)
        version_before = self._db_version
        try:
            execution = self._prepare_close(symbol, quote)
            intent_id = self._stage_protective_execution(symbol, reason, execution)
            self._apply_protective_execution(intent_id)
        except Exception as exc:
            # _close mutates cash/position before its event commits the whole
            # PAPER state.  A storage failure must therefore restore the last
            # durable state, not persist the partially mutated object as BLOCK.
            try:
                self._reload_canonical_state()
            except Exception:
                self._state = state_before
                self._db_version = version_before
            blocked = f"paper_execution_preflight_error:{type(exc).__name__}: {exc}"
            self._trace(symbol, "BLOCK", blocked, phase="protective_exit")
            self._event("BLOCK", blocked, symbol)

    def _stage_protective_execution(
        self,
        symbol: str,
        reason: str,
        execution: Mapping[str, Any],
    ) -> str:
        """Durably stage an exact protective close before settlement/state mutation."""

        position = self._state.get("positions", {}).get(symbol)
        if not isinstance(position, Mapping):
            raise PaperExecutionRejected("paper position is unavailable")
        identity = ":".join(
            (
                self.scope,
                str(symbol).upper(),
                str(position.get("decision_id") or position.get("opened_at") or "legacy"),
                str(reason),
            )
        )
        intent_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:40]
        prepared = dict(execution)
        prepared["trade_id"] = f"paper_protect_{intent_id}"
        prepared["execution_intent_id"] = f"paper_protective:{intent_id}"
        pending = self._state.setdefault("pending_protective_executions", {})
        if pending and intent_id not in pending:
            raise PaperExecutionRejected("an unresolved protective PAPER execution already exists")
        pending[intent_id] = {
            "symbol": str(symbol).upper(),
            "reason": str(reason),
            "execution": prepared,
            "staged_at_ms": self._now_ms(),
        }
        self._persist()
        return intent_id

    def _apply_protective_execution(self, intent_id: str) -> None:
        pending = self._state.get("pending_protective_executions", {})
        intent = pending.get(intent_id) if isinstance(pending, Mapping) else None
        if not isinstance(intent, Mapping) or not isinstance(intent.get("execution"), Mapping):
            raise PaperExecutionRejected("durable protective PAPER execution intent is unavailable")
        execution = dict(intent["execution"])
        execution_intent_id = str(execution.get("execution_intent_id") or "")
        if any(
            str(trade.get("execution_intent_id") or "") == execution_intent_id
            for trade in self._state.get("trades", [])
        ):
            self._complete_protective_execution(intent_id)
            return
        state_before = copy.deepcopy(self._state)
        version_before = self._db_version
        try:
            self._close(
                str(intent.get("symbol") or "").upper(),
                None,
                str(intent.get("reason") or "protective_exit"),
                prepared=execution,
            )
        except Exception:
            try:
                self._reload_canonical_state()
            except Exception:
                self._state = state_before
                self._db_version = version_before
            raise
        self._complete_protective_execution(intent_id)

    def _complete_protective_execution(self, intent_id: str) -> None:
        pending = self._state.get("pending_protective_executions", {})
        if isinstance(pending, dict):
            pending.pop(intent_id, None)
        self._state.pop("pending_protective_recovery_error", None)
        self._persist()

    def _recover_pending_protective_executions(self) -> None:
        pending = self._state.get("pending_protective_executions", {})
        if not isinstance(pending, dict):
            return
        for intent_id in tuple(pending):
            try:
                self._apply_protective_execution(intent_id)
            except Exception as exc:
                self._state["pending_protective_recovery_error"] = (
                    f"{type(exc).__name__}: {exc}"
                )

    def _stage_authorized_execution(
        self,
        *,
        symbol: str,
        side: str,
        reason: str,
        authorization: PaperDecisionAuthorization,
        execution: Mapping[str, Any],
    ) -> None:
        """Durably stage an exact fill before consuming its single-use authority."""

        clean_side = str(side).upper()
        if clean_side not in {"BUY", "SELL"}:
            raise PaperExecutionRejected("authorized PAPER side is invalid")
        decision_id = authorization.decision_id
        intent_id = hashlib.sha256(
            f"{self.scope}:{clean_side}:{decision_id}".encode("utf-8")
        ).hexdigest()[:40]
        prepared = dict(execution)
        prepared["trade_id"] = f"paper_auth_{intent_id}"
        prepared["execution_intent_id"] = f"paper_authorized:{clean_side.lower()}:{decision_id}"
        evidence = self._authorization_evidence(authorization)
        pending = self._state.setdefault("pending_authorized_executions", {})
        if any(
            str(item.get("symbol") or "").upper() == str(symbol).upper()
            and str(item.get("decision_id") or "") != decision_id
            for item in pending.values()
            if isinstance(item, Mapping)
        ):
            raise PaperExecutionRejected(
                "an unresolved authorized PAPER execution already exists for symbol"
            )
        pending[decision_id] = {
            "decision_id": decision_id,
            "symbol": str(symbol).upper(),
            "side": clean_side,
            "reason": str(reason),
            "execution": prepared,
            "authorization_evidence": evidence,
            "staged_at_ms": self._now_ms(),
        }
        self._persist()

    @staticmethod
    def _authorization_evidence(
        authorization: PaperDecisionAuthorization,
    ) -> dict[str, Any]:
        return {
            "decision_id": authorization.decision_id,
            "candidate_id": authorization.candidate_result.candidate.candidate_id,
            "decision_quality_action": authorization.assessment.action,
            "decision_quality_confidence": authorization.assessment.confidence,
            "decision_quality_agreement": authorization.assessment.agreement,
            "general_controller_decision": (
                authorization.candidate_result.general_controller_decision.value
            ),
            "regime": authorization.assessment.regime,
            "canonical_entry_authorized": True,
            "authorization_single_use": True,
        }

    def _apply_authorized_execution(self, decision_id: str) -> None:
        pending = self._state.get("pending_authorized_executions", {})
        intent = pending.get(decision_id) if isinstance(pending, Mapping) else None
        if not isinstance(intent, Mapping):
            raise PaperExecutionRejected("durable authorized PAPER execution intent is unavailable")
        consumption = self.database.get_json(
            self.decision_runtime.consumption_namespace,
            decision_id,
        )
        if consumption is None:
            raise PaperExecutionRejected("PAPER authorization consumption is not durable")
        execution = intent.get("execution")
        evidence = intent.get("authorization_evidence")
        if not isinstance(execution, Mapping) or not isinstance(evidence, Mapping):
            raise PaperExecutionRejected("durable authorized PAPER execution intent is malformed")
        intent_id = str(execution.get("execution_intent_id") or "")
        existing = next(
            (
                trade
                for trade in self._state.get("trades", [])
                if str(trade.get("execution_intent_id") or "") == intent_id
            ),
            None,
        )
        if existing is not None:
            self._complete_authorized_execution(decision_id)
            return

        state_before = copy.deepcopy(self._state)
        version_before = self._db_version
        self._pending_authorization_evidence = dict(evidence)
        try:
            side = str(intent.get("side") or "").upper()
            symbol = str(intent.get("symbol") or "").upper()
            reason = str(intent.get("reason") or "")
            if side == "BUY":
                if symbol in self._state.get("positions", {}):
                    raise PaperExecutionRejected("authorized BUY recovery found an existing position")
                self._open(
                    symbol,
                    None,
                    reason,
                    prepared=dict(execution),
                    entry_context=dict(evidence),
                )
            elif side == "SELL":
                if symbol not in self._state.get("positions", {}):
                    raise PaperExecutionRejected("authorized SELL recovery found no position")
                self._close(
                    symbol,
                    None,
                    reason,
                    prepared=dict(execution),
                    exit_authorization_evidence=dict(evidence),
                )
            else:
                raise PaperExecutionRejected("durable authorized PAPER side is invalid")
        except Exception:
            try:
                self._reload_canonical_state()
            except Exception:
                self._state = state_before
                self._db_version = version_before
            raise
        finally:
            self._pending_authorization_evidence = None
        self._complete_authorized_execution(decision_id)

    def _complete_authorized_execution(self, decision_id: str) -> None:
        pending = self._state.get("pending_authorized_executions", {})
        if isinstance(pending, dict):
            pending.pop(decision_id, None)
        self._state.pop("pending_execution_recovery_error", None)
        self._persist()

    def _reload_canonical_state(self) -> None:
        current = self.database.get_json(self.state_namespace, self.scope)
        if current is None:
            raise RuntimeError("canonical PAPER state disappeared during execution recovery")
        self._db_version = int(current["version"])
        self._state = self._normalize_state(current["value"])
        if not isinstance(self._state.get("pending_authorized_executions"), dict):
            self._state["pending_authorized_executions"] = {}
        if not isinstance(self._state.get("pending_protective_executions"), dict):
            self._state["pending_protective_executions"] = {}

    def _recover_pending_authorized_executions(self) -> None:
        pending = self._state.get("pending_authorized_executions", {})
        if not isinstance(pending, dict) or not pending:
            return
        for decision_id in tuple(pending):
            consumption = self.database.get_json(
                self.decision_runtime.consumption_namespace,
                decision_id,
            )
            if consumption is None:
                intent = pending.get(decision_id)
                evidence = (
                    intent.get("authorization_evidence")
                    if isinstance(intent, Mapping)
                    else None
                )
                candidate_id = (
                    str(evidence.get("candidate_id") or "")
                    if isinstance(evidence, Mapping)
                    else ""
                )
                try:
                    self.decision_runtime.recover_staged_authorization(
                        decision_id,
                        candidate_id,
                        consumed_at_ms=self._now_ms(),
                    )
                except Exception as exc:
                    self._state["pending_execution_recovery_error"] = (
                        f"{type(exc).__name__}: {exc}"
                    )
                    continue
            try:
                self._apply_authorized_execution(decision_id)
            except Exception as exc:
                self._state["pending_execution_recovery_error"] = (
                    f"{type(exc).__name__}: {exc}"
                )

    def _prepare_open(self, symbol: str, quote: Any) -> dict[str, Any]:
        cash = Decimal(str(self._state["cash"]))
        position_percent, recovery_reason = self._entry_position_percent()
        if recovery_reason:
            self._event("WAIT", recovery_reason, symbol)
        budget = min(
            cash * Decimal(str(position_percent)) / Decimal("100"),
            cash / Decimal(max(len(self.stream.symbols), 1)),
        )
        # Recovery size may land under verified paper min_notional after fees.
        # Raise to the instrument minimum when cash can pay it; never invent a live min.
        rules = self.instrument_rules.get(symbol, "spot")
        min_notional = _positive_decimal(rules.min_notional, "minimum notional")
        min_qty = _positive_decimal(rules.min_qty, "minimum quantity")
        qty_step = _positive_decimal(rules.qty_step, "qty step")
        ask = _positive_decimal(getattr(quote, "ask_price", None), "best ask")
        requested_quantity = budget / ask
        if recovery_reason:
            floor_qty = max(min_qty, _step(min_notional / ask, qty_step, ROUND_UP))
            if floor_qty * ask <= cash:
                requested_quantity = max(requested_quantity, floor_qty)
        execution = self._prepare_execution(symbol, quote, Side.BUY, requested_quantity)
        if recovery_reason:
            execution["recovery_size"] = True
            execution["recovery_position_percent"] = float(position_percent)
        return execution

    def _prepare_close(self, symbol: str, quote: Any) -> dict[str, Any]:
        position = self._state["positions"].get(symbol)
        if not isinstance(position, Mapping):
            raise PaperExecutionRejected("paper position is unavailable")
        legacy_quantity = not position.get("paper_execution_semantics")
        execution = self._prepare_execution(
            symbol,
            quote,
            Side.SELL,
            _positive_decimal(position.get("quantity"), "position quantity"),
            preserve_legacy_quantity=legacy_quantity,
        )
        if legacy_quantity:
            execution["legacy_quantity_rules_exception"] = True
        return execution

    def _prepare_execution(
        self,
        symbol: str,
        quote: Any,
        side: Side,
        requested_quantity: Decimal,
        *,
        preserve_legacy_quantity: bool = False,
    ) -> dict[str, Any]:
        rules = self.instrument_rules.get(symbol, "spot")
        if rules.symbol != str(symbol).upper() or rules.category != "spot":
            raise PaperExecutionRejected("verified instrument rules do not match PAPER symbol/category")
        if str(rules.source) != "bybit_v5_instruments_info":
            raise PaperExecutionRejected("verified instrument rules source is invalid")
        if int(rules.fetched_at_ms) <= 0:
            raise PaperExecutionRejected("verified instrument rules timestamp is invalid")
        min_qty = _positive_decimal(rules.min_qty, "minimum quantity")
        min_notional = _positive_decimal(rules.min_notional, "minimum notional")
        if rules.max_market_qty is not None and _positive_decimal(
            rules.max_market_qty, "maximum market quantity"
        ) < min_qty:
            raise PaperExecutionRejected("maximum market quantity is below minimum quantity")
        bid = _positive_decimal(getattr(quote, "bid_price", None), "best bid")
        ask = _positive_decimal(getattr(quote, "ask_price", None), "best ask")
        if ask < bid:
            raise PaperExecutionRejected("best ask is below best bid")
        midpoint = (bid + ask) / Decimal("2")
        quantity = (
            requested_quantity
            if preserve_legacy_quantity
            else _step(requested_quantity, rules.qty_step, ROUND_DOWN)
        )
        if quantity < min_qty:
            raise PaperExecutionRejected("quantity is below verified minimum")
        if rules.max_market_qty is not None and quantity > rules.max_market_qty:
            if preserve_legacy_quantity:
                raise PaperExecutionRejected("legacy position exceeds verified maximum market quantity")
            quantity = _step(rules.max_market_qty, rules.qty_step, ROUND_DOWN)
        if quantity < min_qty:
            raise PaperExecutionRejected("quantity is below verified minimum")

        quote_turnover = _optional_positive_decimal(
            getattr(quote, "volume_24h", None), "24h quote turnover"
        )
        base_volume = None if quote_turnover is None else float(quote_turnover / midpoint)
        event = MarketEvent(
            timestamp_ms=int(getattr(quote, "received_at_unix_ms", 0) or 0),
            symbol=str(symbol).upper(),
            bid=float(bid),
            ask=float(ask),
            source=str(getattr(quote, "source", "bybit_websocket_v5")),
            volume=base_volume,
        )
        estimated = self.cost_model.estimate(
            event,
            side=side,
            quantity=float(quantity),
            liquidity_role="taker",
        )
        fee_rate = _bounded_decimal(
            estimated.fee_rate,
            "fee rate",
            minimum=Decimal("0"),
            maximum=Decimal("0.05"),
        )
        participation = _bounded_decimal(
            estimated.participation_rate,
            "participation rate",
            minimum=Decimal("0"),
            maximum=Decimal(str(self.cost_model.max_participation_rate)),
        )
        effective_slippage_bps = _bounded_decimal(
            estimated.effective_slippage_bps,
            "effective slippage bps",
            minimum=Decimal("0"),
            maximum=Decimal("10000"),
        )
        raw_execution_price = _positive_decimal(estimated.execution_price, "execution price")
        bbo = ask if side is Side.BUY else bid
        if side is Side.BUY and raw_execution_price < bbo:
            raise PaperExecutionRejected("BUY execution cannot improve executable ask")
        if side is Side.SELL and raw_execution_price > bbo:
            raise PaperExecutionRejected("SELL execution cannot improve executable bid")
        execution_price = _step(
            raw_execution_price,
            rules.tick_size,
            ROUND_UP if side is Side.BUY else ROUND_DOWN,
        )
        if rules.min_price is not None and execution_price < rules.min_price:
            raise PaperExecutionRejected("execution price is below verified minimum")
        if rules.max_price is not None and execution_price > rules.max_price:
            raise PaperExecutionRejected("execution price exceeds verified maximum")
        notional = execution_price * quantity
        if notional < min_notional:
            raise PaperExecutionRejected("order notional is below verified minimum")

        spread_cost = abs(bbo - midpoint) * quantity
        slippage_cost = abs(execution_price - bbo) * quantity
        base_rate = Decimal(str(self.cost_model.slippage_bps)) / Decimal("10000")
        base_execution = (
            bbo * (Decimal("1") + base_rate)
            if side is Side.BUY
            else bbo / (Decimal("1") + base_rate)
        )
        estimated_impact = abs(
            _positive_decimal(estimated.execution_price, "estimated execution price")
            - base_execution
        ) * quantity
        impact_cost = min(slippage_cost, estimated_impact)
        fee = notional * fee_rate
        return {
            "side": side.value,
            "quantity": float(quantity),
            "reference_price": float(midpoint),
            "bbo_price": float(bbo),
            "execution_price": float(execution_price),
            "notional": float(notional),
            "fee": float(fee),
            "spread_cost": float(spread_cost),
            "slippage_cost": float(slippage_cost),
            "impact_cost": float(impact_cost),
            "impact_cost_included_in_slippage": True,
            "participation_rate": float(participation),
            "effective_slippage_bps": float(effective_slippage_bps),
            "fee_rate": float(fee_rate),
            "instrument_rules_fetched_at_ms": int(rules.fetched_at_ms),
            "instrument_rules_source": str(rules.source),
            "qty_step": str(rules.qty_step),
            "tick_size": str(rules.tick_size),
            "min_qty": str(min_qty),
            "min_notional": str(min_notional),
            "paper_execution_semantics": "bybit_spot_taker_v2",
            "execution_source": "bybit_rest_bbo+execution_cost_model",
        }

    def _open(
        self,
        symbol: str,
        quote: Any,
        reason: str,
        *,
        prepared: dict[str, Any] | None = None,
        entry_context: Mapping[str, Any] | None = None,
    ) -> None:
        execution = prepared or self._prepare_open(symbol, quote)
        cash = Decimal(str(self._state["cash"]))
        required = Decimal(str(execution["notional"])) + Decimal(str(execution["fee"]))
        if required > cash:
            raise PaperExecutionRejected("paper cash is insufficient for notional and fee")
        opened_at = self._now()
        self._state["cash"] = float(cash - required)
        position = {
            "quantity": execution["quantity"],
            "entry_price": execution["execution_price"],
            "entry_reference_price": execution["reference_price"],
            "opened_at": opened_at,
            "entry_fee": execution["fee"],
            "entry_spread_cost": execution["spread_cost"],
            "entry_slippage_cost": execution["slippage_cost"],
            "entry_impact_cost": execution["impact_cost"],
            "paper_execution_semantics": execution["paper_execution_semantics"],
            "reason": reason,
        }
        if entry_context:
            position.update(
                {
                    "decision_id": str(entry_context.get("decision_id") or ""),
                    "candidate_id": str(entry_context.get("candidate_id") or ""),
                    "evidence_class": "verified_market",
                    "verified_market_data": True,
                    "regime": str(entry_context.get("regime") or "unknown"),
                }
            )
            shadow = self._state.get("v2_shadow_records", {}).get(position["decision_id"])
            if isinstance(shadow, Mapping):
                position["v2_shadow_snapshot_id"] = shadow.get("snapshot_id")
                position["v2_shadow_evidence_hash"] = shadow.get("evidence_hash")
        self._state["positions"][symbol] = position
        self._state["total_fees"] += execution["fee"]
        self._pending_execution = execution
        try:
            self._trade(
                symbol,
                "BUY",
                execution["quantity"],
                execution["execution_price"],
                execution["fee"],
                reason,
                None,
            )
        finally:
            self._pending_execution = None

    def _close(
        self,
        symbol: str,
        quote: Any,
        reason: str,
        *,
        exit_authorization: PaperDecisionAuthorization | None = None,
        exit_authorization_evidence: Mapping[str, Any] | None = None,
        prepared: dict[str, Any] | None = None,
    ) -> None:
        position = dict(self._state["positions"].get(symbol) or {})
        execution = prepared or self._prepare_close(symbol, quote)
        if (
            Decimal(str(execution["quantity"])) != Decimal(str(position.get("quantity")))
            and not execution.get("legacy_quantity_rules_exception")
        ):
            raise PaperExecutionRejected("existing position quantity is not aligned to verified qtyStep")
        exit_evidence = dict(exit_authorization_evidence or {})
        if exit_authorization is not None:
            exit_evidence = self._authorization_evidence(exit_authorization)
        entry_has_realistic_costs = bool(position.get("paper_execution_semantics"))
        self._pending_exit_context = {
            "decision_id": str(position.get("decision_id") or "").strip(),
            "candidate_id": str(position.get("candidate_id") or "").strip(),
            "entry_price": float(position.get("entry_price", 0.0) or 0.0),
            "entry_fee": float(position.get("entry_fee", 0.0) or 0.0),
            "entry_reference_price": float(
                position.get("entry_reference_price", position.get("entry_price", 0.0)) or 0.0
            ),
            "entry_spread_cost": float(position.get("entry_spread_cost", 0.0) or 0.0),
            "entry_slippage_cost": float(position.get("entry_slippage_cost", 0.0) or 0.0),
            "entry_impact_cost": float(position.get("entry_impact_cost", 0.0) or 0.0),
            "entry_spread_cost_unknown": not entry_has_realistic_costs,
            "entry_slippage_cost_unknown": not entry_has_realistic_costs,
            "legacy_quantity_rules_exception": bool(
                execution.get("legacy_quantity_rules_exception")
            ),
            "exit_decision_id": str(exit_evidence.get("decision_id") or ""),
            "exit_candidate_id": str(exit_evidence.get("candidate_id") or ""),
        }
        try:
            quantity = Decimal(str(execution["quantity"]))
            proceeds = Decimal(str(execution["execution_price"])) * quantity
            gross = (
                Decimal(str(execution["reference_price"]))
                - Decimal(str(self._pending_exit_context["entry_reference_price"]))
            ) * quantity
            total_spread = Decimal(str(self._pending_exit_context["entry_spread_cost"])) + Decimal(
                str(execution["spread_cost"])
            )
            total_slippage = Decimal(str(self._pending_exit_context["entry_slippage_cost"])) + Decimal(
                str(execution["slippage_cost"])
            )
            total_fees = Decimal(str(self._pending_exit_context["entry_fee"])) + Decimal(
                str(execution["fee"])
            )
            net = gross - total_spread - total_slippage - total_fees
            self._state["positions"].pop(symbol)
            self._state["cash"] += float(proceeds - Decimal(str(execution["fee"])))
            self._state["realized_pnl"] += float(net)
            self._state["total_fees"] += execution["fee"]
            execution["gross_pnl"] = float(gross)
            self._record_last_close(symbol, execution, self._pending_exit_context)
            self._pending_execution = execution
            self._trade(
                symbol,
                "SELL",
                execution["quantity"],
                execution["execution_price"],
                execution["fee"],
                reason,
                float(net),
            )
            self._bind_last_close_trade_id(symbol)
            self._trace(
                symbol,
                "SELL",
                reason,
                phase="protective_exit",
                decision_id=self._pending_exit_context.get("decision_id") or None,
            )
        finally:
            self._pending_execution = None
            self._pending_exit_context = None

    def _trade(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        fee: float,
        reason: str,
        net_pnl: float | None,
    ) -> None:
        """Build the complete council trade before the base event persists it."""

        now = self._now()
        item: dict[str, Any] = {
            "trade_id": new_trade_id(),
            "created_at_ms": self._now_ms(),
            "time": now,
            "symbol": str(symbol).strip().upper(),
            "side": side,
            "quantity": float(quantity),
            "price": float(price),
            "fee": float(fee),
            "net_pnl": None if net_pnl is None else float(net_pnl),
            "reason": str(reason),
            "source": "bybit_websocket",
            "verified_market_data": True,
        }
        if self._pending_execution:
            item.update(self._pending_execution)
            item["price"] = float(self._pending_execution["execution_price"])
            item["gross_pnl"] = self._pending_execution.get("gross_pnl")
            item["source"] = "bybit_websocket_v5+bybit_rest_bbo"

        authorization_evidence = self._pending_authorization_evidence
        if side == "BUY" and authorization_evidence is not None:
            item.update(dict(authorization_evidence))
            item.update(evidence_class="verified_market", verified_market_data=True)
            shadow = self._state.get("v2_shadow_records", {}).get(
                str(authorization_evidence.get("decision_id") or "")
            )
            if isinstance(shadow, Mapping):
                item["v2_shadow_snapshot_id"] = shadow.get("snapshot_id")
                item["v2_shadow_evidence_hash"] = shadow.get("evidence_hash")
                item["v2_shadow_execution_authority"] = False

        if side == "SELL" and self._pending_exit_context:
            decision_id = self._pending_exit_context.get("decision_id", "")
            candidate_id = self._pending_exit_context.get("candidate_id", "")
            if decision_id:
                item.update(
                    {
                        "decision_id": decision_id,
                        "candidate_id": candidate_id or decision_id,
                        "evidence_class": "verified_market",
                        "verified_market_data": True,
                        "canonical_exit_protective": True,
                    }
                )
                exit_decision_id = self._pending_exit_context.get("exit_decision_id", "")
                if exit_decision_id:
                    item.update(
                        {
                            "exit_authorization_decision_id": exit_decision_id,
                            "exit_authorization_candidate_id": self._pending_exit_context.get(
                                "exit_candidate_id", exit_decision_id
                            ),
                            "exit_authorization_single_use": True,
                            "canonical_exit_protective": False,
                        }
                    )
                net = float(net_pnl or 0.0)
                item["entry_spread_cost_unknown"] = bool(
                    self._pending_exit_context.get("entry_spread_cost_unknown")
                )
                item["entry_slippage_cost_unknown"] = bool(
                    self._pending_exit_context.get("entry_slippage_cost_unknown")
                )
                item["legacy_quantity_rules_exception"] = bool(
                    self._pending_exit_context.get("legacy_quantity_rules_exception")
                )
                self._settle_or_mark_pending(item, decision_id=decision_id, net_pnl=net)

                shadow = self._state.get("v2_shadow_records", {}).get(decision_id)
                if isinstance(shadow, Mapping):
                    try:
                        settled_shadow = attach_paper_settlement(
                            shadow,
                            settled_at_ms=item["created_at_ms"],
                            side=side,
                            quantity=float(quantity),
                            entry_price=float(self._pending_exit_context.get("entry_price", 0.0) or 0.0),
                            exit_price=float(price),
                            entry_fee=float(self._pending_exit_context.get("entry_fee", 0.0) or 0.0),
                            exit_fee=float(fee),
                            net_pnl=net,
                            slippage_cost=float(
                                self._pending_exit_context.get("entry_slippage_cost", 0.0) or 0.0
                            ) + float(item.get("slippage_cost", 0.0) or 0.0),
                        )
                        self._state["v2_shadow_records"][decision_id] = settled_shadow
                        item["v2_shadow_snapshot_id"] = settled_shadow["snapshot_id"]
                        item["v2_shadow_evidence_hash"] = settled_shadow["evidence_hash"]
                        item["v2_shadow_execution_authority"] = False
                        item["v2_learning_candidate_stage"] = "candidate"
                    except Exception as exc:
                        item["v2_shadow_settlement_error"] = f"{type(exc).__name__}: {exc}"

        self._state["trades"].append(item)
        self._state["trades"] = self._state["trades"][-500:]
        self._event(side, reason, symbol)

    def _settle_or_mark_pending(
        self,
        trade: dict[str, Any],
        *,
        decision_id: str,
        net_pnl: float,
    ) -> None:
        """Persist V2 settlement, retaining a retry marker on transient failure."""

        try:
            settlement = self.decision_runtime.settle_exit(
                decision_id,
                net_pnl=net_pnl,
                drawdown_contribution=max(0.0, -net_pnl),
            )
        except Exception as exc:
            trade["decision_settlement_error"] = f"{type(exc).__name__}: {exc}"
            trade["settlement_retry_pending"] = True
            return

        trade["decision_settlement"] = settlement
        trade["reputation_recorded"] = bool(settlement.get("reputation_recorded"))
        trade.pop("decision_settlement_error", None)
        trade.pop("settlement_retry_pending", None)

    def _recover_pending_settlements(self) -> None:
        """Retry explicitly durable pending settlements once after a restart."""

        trades = self._state.get("trades")
        if not isinstance(trades, list):
            return
        for trade in trades:
            if not isinstance(trade, dict) or trade.get("settlement_retry_pending") is not True:
                continue
            decision_id = str(trade.get("decision_id") or "").strip()
            net_pnl = trade.get("net_pnl")
            if not decision_id or net_pnl is None:
                continue
            try:
                parsed_net_pnl = float(net_pnl)
            except (TypeError, ValueError):
                continue
            self._settle_or_mark_pending(
                trade,
                decision_id=decision_id,
                net_pnl=parsed_net_pnl,
            )

    def _suppress_wait_event(
        self,
        reason: str,
        symbol: str | None,
        *,
        created_at_ms: int,
    ) -> bool:
        """Emit WAIT at most every five minutes unless its reason changes.

        The previous base implementation keyed timestamps by ``symbol|reason``.
        That suppressed an A→B→A reason transition if the second A happened
        within five minutes. Canonical runtime evidence must show every reason
        transition immediately, while repeated identical WAIT noise is bounded.
        """
        scope = symbol or "*"
        last_reason = self._state.setdefault("wait_event_last_reason_by_symbol", {})
        last_emitted = self._state.setdefault("wait_event_last_emitted_ms_by_symbol", {})
        if not isinstance(last_reason, dict):
            last_reason = {}
            self._state["wait_event_last_reason_by_symbol"] = last_reason
        if not isinstance(last_emitted, dict):
            last_emitted = {}
            self._state["wait_event_last_emitted_ms_by_symbol"] = last_emitted

        previous_reason = str(last_reason.get(scope, ""))
        previous_ms = int(last_emitted.get(scope, 0) or 0)
        minimum_ms = int(self.wait_event_min_interval_seconds * 1000)
        if previous_reason == reason and previous_ms > 0 and created_at_ms - previous_ms < minimum_ms:
            self._state["suppressed_wait_events"] = int(
                self._state.get("suppressed_wait_events", 0) or 0
            ) + 1
            return True

        last_reason[scope] = reason
        last_emitted[scope] = created_at_ms
        if len(last_emitted) > 200:
            newest_scopes = {
                key
                for key, _ in sorted(
                    last_emitted.items(),
                    key=lambda item: int(item[1]),
                    reverse=True,
                )[:200]
            }
            self._state["wait_event_last_emitted_ms_by_symbol"] = {
                key: value for key, value in last_emitted.items() if key in newest_scopes
            }
            self._state["wait_event_last_reason_by_symbol"] = {
                key: value for key, value in last_reason.items() if key in newest_scopes
            }
        return False

    def _record_last_close(
        self,
        symbol: str,
        execution: Mapping[str, Any],
        exit_context: Mapping[str, Any] | None,
    ) -> None:
        """Persist restart-safe last-close evidence used only by the BUY anti-churn gate."""

        context = dict(exit_context or {})
        closes = self._state.setdefault("last_close_by_symbol", {})
        if not isinstance(closes, dict):
            closes = {}
            self._state["last_close_by_symbol"] = closes
        closes[str(symbol).upper()] = {
            "closed_at_ms": self._now_ms(),
            "close_price": float(execution.get("execution_price") or 0.0),
            "decision_id": str(context.get("decision_id") or ""),
            "candidate_id": str(context.get("candidate_id") or ""),
            "fees": float(context.get("entry_fee") or 0.0) + float(execution.get("fee") or 0.0),
            "spread_cost": float(context.get("entry_spread_cost") or 0.0)
            + float(execution.get("spread_cost") or 0.0),
            "slippage_cost": float(context.get("entry_slippage_cost") or 0.0)
            + float(execution.get("slippage_cost") or 0.0),
            "side": "SELL",
            "trade_id": "",
            "quantity": float(execution.get("quantity") or 0.0),
        }

    def _bind_last_close_trade_id(self, symbol: str) -> None:
        trades = self._state.get("trades") or []
        if not trades:
            return
        last = trades[-1]
        if str(last.get("symbol") or "").upper() != str(symbol).upper():
            return
        if str(last.get("side") or "").upper() != "SELL":
            return
        closes = self._state.get("last_close_by_symbol")
        if not isinstance(closes, dict):
            return
        row = closes.get(str(symbol).upper())
        if isinstance(row, dict):
            row["trade_id"] = str(last.get("trade_id") or "")
            row["closed_at_ms"] = int(last.get("created_at_ms") or row.get("closed_at_ms") or 0)

    def _anti_churn_buy_block_reason(
        self,
        symbol: str,
        quote: Any,
        authorization: PaperDecisionAuthorization,
        *,
        proposal: CouncilEntryProposal | None = None,
    ) -> str | None:
        """Return an auditable BUY block reason, or None if a new entry may proceed.

        Protective SELL and authorized SELL of an existing long never call this.
        """

        turnover = self._anti_churn_turnover_reason(symbol)
        if turnover:
            return turnover

        last = self._last_close_for(symbol)
        if last is None:
            return None

        try:
            round_trip = self._estimate_entry_round_trip(symbol, quote, last)
        except Exception as exc:
            return (
                f"{self.ANTI_CHURN_COST_NOT_COVERED}: round-trip cost estimate unavailable "
                f"({type(exc).__name__}: {exc})"
            )
        packet = proposal.evidence_packet if proposal is not None else None
        estimate_qty = self._anti_churn_quantity(quote, last)
        current_mid = self._quote_mid(quote)
        # Council packet estimated_fees/slippage are percent-of-price
        # (fee_percent). Convert to USDT so a 100 USDT book is not judged
        # against a leftover 10_000-scale absolute floor.
        notional = current_mid * estimate_qty if current_mid > 0 else 0.0
        packet_percent = self._packet_reported_cost(authorization, packet)
        packet_cost = packet_percent / 100.0 * notional if packet_percent > 0 and notional > 0 else 0.0
        all_in = max(float(round_trip.all_in), packet_cost)
        required = all_in * self.ANTI_CHURN_COST_MARGIN
        last_price = float(last.get("close_price") or 0.0)
        price_move_value = abs(current_mid - last_price) * estimate_qty
        edge = self._explicit_expected_edge(authorization, packet)
        same_identity = self._same_buy_identity(last, authorization)

        if same_identity:
            return (
                f"{self.ANTI_CHURN_REENTRY}: same decision_id/candidate_id as last close "
                f"({last.get('decision_id') or last.get('candidate_id')}); "
                f"all_in={all_in:.8f} required={required:.8f}"
            )

        if edge is not None:
            if edge + 1e-12 < required:
                return (
                    f"{self.ANTI_CHURN_COST_NOT_COVERED}: expected_edge={edge:.8f} "
                    f"does not cover {self.ANTI_CHURN_COST_MARGIN}x all-in round-trip "
                    f"cost {all_in:.8f} (required {required:.8f})"
                )
            return None

        # Fail-closed hysteresis: no reliable expected-edge evidence, so the
        # market itself must have moved enough to cover all-in cost + margin.
        if price_move_value + 1e-12 < required:
            return (
                f"{self.ANTI_CHURN_COST_NOT_COVERED}: price move {price_move_value:.8f} "
                f"does not cover {self.ANTI_CHURN_COST_MARGIN}x all-in round-trip "
                f"cost {all_in:.8f} (required {required:.8f}); fees+spread+slippage participate"
            )
        return None

    def _anti_churn_turnover_reason(self, symbol: str) -> str | None:
        now_ms = self._now_ms()
        cutoff = now_ms - self.ANTI_CHURN_TURNOVER_WINDOW_MS
        clean = str(symbol).upper()
        window: list[dict[str, Any]] = []
        for trade in self._state.get("trades") or []:
            if not isinstance(trade, dict):
                continue
            if str(trade.get("symbol") or "").upper() != clean:
                continue
            created = int(trade.get("created_at_ms") or 0)
            if created >= cutoff:
                window.append(trade)
        round_trips = sum(
            1 for trade in window if str(trade.get("side") or "").upper() == "SELL"
        )
        fees = 0.0
        for trade in window:
            try:
                fee = float(trade.get("fee") or 0.0)
            except (TypeError, ValueError):
                fee = 0.0
            if math.isfinite(fee) and fee > 0:
                fees += fee
        equity = float(self._state.get("equity") or self._state.get("cash") or 0.0)
        if round_trips >= self.ANTI_CHURN_MAX_ROUND_TRIPS:
            return (
                f"{self.ANTI_CHURN_TURNOVER_LIMIT}: {round_trips} round trips in "
                f"{self.ANTI_CHURN_TURNOVER_WINDOW_MS}ms window"
            )
        if equity > 0 and fees > equity * self.ANTI_CHURN_FEE_EQUITY_FRACTION:
            return (
                f"{self.ANTI_CHURN_TURNOVER_LIMIT}: window fees {fees:.8f} exceed "
                f"{self.ANTI_CHURN_FEE_EQUITY_FRACTION} of equity {equity:.8f}"
            )
        return None

    def _last_close_for(self, symbol: str) -> dict[str, Any] | None:
        closes = self._state.get("last_close_by_symbol")
        if not isinstance(closes, dict):
            return None
        row = closes.get(str(symbol).upper())
        if not isinstance(row, dict):
            return None
        if float(row.get("close_price") or 0.0) <= 0:
            return None
        return row

    def _same_buy_identity(
        self,
        last: Mapping[str, Any],
        authorization: PaperDecisionAuthorization,
    ) -> bool:
        decision_id = str(authorization.decision_id or "")
        candidate = authorization.candidate_result.candidate
        candidate_id = str(getattr(candidate, "candidate_id", "") or "")
        last_decision = str(last.get("decision_id") or "")
        last_candidate = str(last.get("candidate_id") or "")
        if decision_id and last_decision and decision_id == last_decision:
            return True
        if candidate_id and last_candidate and candidate_id == last_candidate:
            return True
        return False

    def _explicit_expected_edge(
        self,
        authorization: PaperDecisionAuthorization,
        packet: Any,
    ) -> float | None:
        """Use a packet/candidate expected-edge field if present. Never invent one."""

        candidate = authorization.candidate_result.candidate
        sources = (
            packet,
            candidate,
            authorization,
            getattr(authorization, "assessment", None),
        )
        for source in sources:
            value = self._read_finite_field(
                source,
                "expected_edge",
                "expected_pnl",
                "expected_gross_edge",
                "estimated_edge",
            )
            if value is not None:
                return value
        return None

    def _packet_reported_cost(
        self,
        authorization: PaperDecisionAuthorization,
        packet: Any,
    ) -> float:
        candidate = authorization.candidate_result.candidate
        total = 0.0
        found = False
        for source in (packet, candidate):
            for field in ("estimated_fees", "estimated_slippage"):
                value = self._read_finite_field(source, field)
                if value is not None and value > 0:
                    total += value
                    found = True
            if found:
                break
        return total if found else 0.0

    @staticmethod
    def _read_finite_field(source: Any, *names: str) -> float | None:
        if source is None:
            return None
        for name in names:
            if isinstance(source, Mapping) and name in source:
                raw = source.get(name)
            else:
                raw = getattr(source, name, None)
            if raw is None:
                continue
            try:
                parsed = float(raw)
            except (TypeError, ValueError):
                continue
            if math.isfinite(parsed):
                return parsed
        return None

    def _anti_churn_quantity(self, quote: Any, last: Mapping[str, Any] | None) -> float:
        ask = float(getattr(quote, "ask_price", None) or getattr(quote, "price", 0.0) or 0.0)
        cash = float(self._state.get("cash") or 0.0)
        position_percent, recovery_reason = self._entry_position_percent()
        budget = min(
            cash * float(position_percent) / 100.0,
            cash / max(len(self.stream.symbols), 1),
        )
        symbol = str(getattr(quote, "symbol", "") or "").strip().upper()
        if recovery_reason and symbol:
            try:
                min_notional = float(self.instrument_rules.get(symbol, "spot").min_notional)
            except Exception:
                min_notional = 0.0
            if min_notional > 0 and budget < min_notional <= cash:
                budget = min_notional
        intended = budget / ask if ask > 0 else 0.0
        last_qty = float((last or {}).get("quantity") or 0.0)
        quantity = intended if intended > 0 else last_qty
        if not math.isfinite(quantity) or quantity <= 0:
            raise PaperExecutionRejected("anti-churn quantity is unavailable")
        return quantity

    def _quote_mid(self, quote: Any) -> float:
        bid = float(getattr(quote, "bid_price", None) or 0.0)
        ask = float(getattr(quote, "ask_price", None) or 0.0)
        if bid > 0 and ask > 0 and ask >= bid:
            return (bid + ask) / 2.0
        price = float(getattr(quote, "price", 0.0) or 0.0)
        if price <= 0:
            raise PaperExecutionRejected("anti-churn quote mid is unavailable")
        return price

    def _estimate_entry_round_trip(
        self,
        symbol: str,
        quote: Any,
        last: Mapping[str, Any] | None,
    ):
        quantity = self._anti_churn_quantity(quote, last)
        bid = float(getattr(quote, "bid_price", None) or 0.0)
        ask = float(getattr(quote, "ask_price", None) or 0.0)
        if bid <= 0 or ask <= 0 or ask < bid:
            raise PaperExecutionRejected("anti-churn BBO is unavailable")
        midpoint = (bid + ask) / 2.0
        volume = None
        turnover = getattr(quote, "volume_24h", None)
        if turnover not in (None, ""):
            try:
                quote_turnover = float(turnover)
            except (TypeError, ValueError):
                quote_turnover = 0.0
            if math.isfinite(quote_turnover) and quote_turnover > 0 and midpoint > 0:
                volume = quote_turnover / midpoint
        event = MarketEvent(
            timestamp_ms=int(getattr(quote, "received_at_unix_ms", 0) or self._now_ms()),
            symbol=str(symbol).upper(),
            bid=bid,
            ask=ask,
            source=str(getattr(quote, "source", "bybit_websocket_v5") or "bybit_websocket_v5"),
            volume=volume,
        )
        try:
            return self.cost_model.estimate_round_trip(event, quantity=quantity)
        except ValueError:
            event_no_volume = MarketEvent(
                timestamp_ms=event.timestamp_ms,
                symbol=event.symbol,
                bid=event.bid,
                ask=event.ask,
                source=event.source,
            )
            return self.cost_model.estimate_round_trip(event_no_volume, quantity=quantity)

    def _proposal_state_snapshot(self) -> dict[str, Any]:
        return {
            "cash": float(self._state.get("cash", 0.0)),
            "equity": float(self._state.get("equity", 0.0)),
            "peak_equity": float(self._state.get("peak_equity", self._state.get("equity", 0.0))),
            "initial_cash": float(self.initial_cash),
            "realized_pnl": float(self._state.get("realized_pnl", 0.0)),
            "unrealized_pnl": float(self._state.get("unrealized_pnl", 0.0)),
            "total_fees": float(self._state.get("total_fees", 0.0)),
            "open_symbols": tuple(sorted(self._state.get("positions", {}).keys())),
            "execution_authority": False,
        }

    def snapshot(self) -> dict[str, Any]:
        state = super().snapshot()
        traces = read_decision_traces(self.database, self.stream.symbols)
        shadow_records = state.get("v2_shadow_records", {})
        if not isinstance(shadow_records, dict):
            shadow_records = {}
        state["decision_mode"] = "CANONICAL_COUNCIL_REQUIRED"
        state["entry_without_authorization_allowed"] = False
        state["protective_exit_without_new_council_allowed"] = True
        state["authorization_single_use"] = True
        state["verified_exit_learning"] = True
        state["decision_runtime"] = self.decision_runtime.status()
        state["decision_traces"] = traces
        state["latest_decision_trace"] = traces[0] if traces else None
        state["v2_shadow_enabled"] = True
        state["v2_shadow_execution_authority"] = False
        state["v2_shadow_record_count"] = len(shadow_records)
        state["v2_shadow_latest"] = max(
            shadow_records.values(),
            key=lambda row: int(row.get("decision_ts_ms", 0) or 0),
            default=None,
        )
        return state


__all__ = [
    "CouncilAuthorizedPaperLoop",
    "CouncilEntryProposal",
    "PaperExecutionRejected",
    "ProposalProvider",
    "ShadowGateProvider",
]


def _positive_decimal(value: Any, name: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except Exception as exc:
        raise PaperExecutionRejected(f"{name} is invalid") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise PaperExecutionRejected(f"{name} must be positive and finite")
    return parsed


def _optional_positive_decimal(value: Any, name: str) -> Decimal | None:
    if value in (None, ""):
        return None
    return _positive_decimal(value, name)


def _bounded_decimal(
    value: Any,
    name: str,
    *,
    minimum: Decimal,
    maximum: Decimal,
) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except Exception as exc:
        raise PaperExecutionRejected(f"{name} is invalid") from exc
    if not parsed.is_finite() or parsed < minimum or parsed > maximum:
        raise PaperExecutionRejected(f"{name} must be within {minimum}..{maximum}")
    return parsed


def _step(value: Decimal, step: Decimal, rounding: str) -> Decimal:
    if not step.is_finite() or step <= 0:
        raise PaperExecutionRejected("verified instrument step is invalid")
    return (value / step).to_integral_value(rounding=rounding) * step
