"""Council-authorized autonomous paper loop.

New entries are impossible without a canonical Decision Quality assessment and a
validated TradingCandidate. Protective exits remain local and immediate because
capital preservation must not wait for a new council round.
"""
from __future__ import annotations

from dataclasses import dataclass
from threading import Thread
from typing import Any, Callable, Mapping, Sequence

from decision_quality import CandidateEvidencePacket
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


class CouncilAuthorizedPaperLoop(AutonomousPaperLoop):
    """Autonomous paper loop whose new entries require council authorization."""

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
        self._pending_authorization: PaperDecisionAuthorization | None = None
        self._pending_exit_context: dict[str, Any] | None = None
        self._state["peak_equity"] = max(
            float(self._state.get("peak_equity", 0.0) or 0.0),
            float(self._state.get("equity", 0.0) or 0.0),
        )
        if not isinstance(self._state.get("v2_shadow_records"), dict):
            self._state["v2_shadow_records"] = {}
        if not isinstance(self._state.get("v2_shadow_errors"), list):
            self._state["v2_shadow_errors"] = []
        # A close is already an immutable PAPER fact when the process comes
        # back.  Recover only explicitly marked, previously failed settlement
        # writes; do not infer settlements from arbitrary historical trades.
        self._recover_pending_settlements()

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
                        self.decision_runtime.consume_authorization(
                            authorization,
                            consumed_at_ms=self._now_ms(),
                        )
                    except Exception as exc:
                        reason = f"authorization_consumption_error:{type(exc).__name__}: {exc}"
                        self._trace(symbol, "BLOCK", reason, phase="authorization_consumption")
                        self._event("BLOCK", reason, symbol)
                        continue

                    self._close(
                        symbol,
                        quote.price,
                        f"canonical_council_sell:{authorization.decision_id}",
                        exit_authorization=authorization,
                    )
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

                self._pending_authorization = authorization
                try:
                    self._open(
                        symbol,
                        quote.price,
                        f"canonical_council_allow:{authorization.decision_id}",
                    )
                    position = self._state["positions"].get(symbol)
                    if position is None:
                        reason = "authorized entry could not allocate a safe paper budget"
                        self._trace(symbol, "BLOCK", reason, phase="virtual_execution")
                        self._event("BLOCK", reason, symbol)
                        continue
                    position["decision_id"] = authorization.decision_id
                    position["candidate_id"] = authorization.candidate_result.candidate.candidate_id
                    position["evidence_class"] = "verified_market"
                    position["verified_market_data"] = True
                    position["regime"] = authorization.assessment.regime
                    shadow = self._state.get("v2_shadow_records", {}).get(authorization.decision_id)
                    if isinstance(shadow, Mapping):
                        position["v2_shadow_snapshot_id"] = shadow.get("snapshot_id")
                        position["v2_shadow_evidence_hash"] = shadow.get("evidence_hash")
                    self._trace(
                        symbol,
                        "BUY",
                        f"canonical council authorization consumed and paper BUY opened: {authorization.decision_id}",
                        phase="virtual_execution",
                        decision_id=authorization.decision_id,
                        authorized=True,
                    )
                finally:
                    self._pending_authorization = None

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
        position = self._state["positions"].get(symbol)
        if not position:
            return
        entry = float(position["entry_price"])
        move = (float(quote.price) - entry) / entry * 100
        change = quote.change_24h_percent
        if move <= -self.stop_loss_percent:
            self._close(symbol, quote.price, "protective_stop_loss")
        elif move >= self.take_profit_percent:
            self._close(symbol, quote.price, "protective_take_profit")
        elif change is not None and change <= self.exit_change_percent:
            self._close(symbol, quote.price, "protective_momentum_exit")

    def _close(
        self,
        symbol: str,
        price: float,
        reason: str,
        *,
        exit_authorization: PaperDecisionAuthorization | None = None,
    ) -> None:
        position = dict(self._state["positions"].get(symbol) or {})
        self._pending_exit_context = {
            "decision_id": str(position.get("decision_id") or "").strip(),
            "candidate_id": str(position.get("candidate_id") or "").strip(),
            "entry_price": float(position.get("entry_price", 0.0) or 0.0),
            "entry_fee": float(position.get("entry_fee", 0.0) or 0.0),
            "exit_decision_id": (
                exit_authorization.decision_id if exit_authorization is not None else ""
            ),
            "exit_candidate_id": (
                exit_authorization.candidate_result.candidate.candidate_id
                if exit_authorization is not None
                else ""
            ),
        }
        try:
            super()._close(symbol, price, reason)
            self._trace(
                symbol,
                "SELL",
                reason,
                phase="protective_exit",
                decision_id=self._pending_exit_context.get("decision_id") or None,
            )
        finally:
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

        if side == "BUY" and self._pending_authorization is not None:
            authorization = self._pending_authorization
            item.update(
                {
                    "decision_id": authorization.decision_id,
                    "candidate_id": authorization.candidate_result.candidate.candidate_id,
                    "evidence_class": "verified_market",
                    "verified_market_data": True,
                    "decision_quality_action": authorization.assessment.action,
                    "decision_quality_confidence": authorization.assessment.confidence,
                    "decision_quality_agreement": authorization.assessment.agreement,
                    "general_controller_decision": authorization.candidate_result.general_controller_decision.value,
                    "canonical_entry_authorized": True,
                    "authorization_single_use": True,
                }
            )
            shadow = self._state.get("v2_shadow_records", {}).get(authorization.decision_id)
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
                            # Current paper execution fills at the supplied verified quote;
                            # there is no separate simulated slippage charge in this loop.
                            slippage_cost=0.0,
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
    "ProposalProvider",
    "ShadowGateProvider",
]
