"""Council-authorized autonomous paper loop.

New entries are impossible without a canonical Decision Quality assessment and a
validated TradingCandidate. Protective exits remain local and immediate because
capital preservation must not wait for a new council round.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from decision_quality import CandidateEvidencePacket
from trading_candidate import TradingDecision

from .canonical_runtime import CanonicalPaperDecisionRuntime, PaperDecisionAuthorization
from .loop import AutonomousPaperLoop
from .trade_identity import new_trade_id


@dataclass(frozen=True, slots=True)
class CouncilEntryProposal:
    decision_id: str
    agent_payloads: Sequence[Mapping[str, Any]]
    evidence_packet: CandidateEvidencePacket
    general_controller_decision: TradingDecision
    regime: str = "unknown"


ProposalProvider = Callable[[str, Any, Mapping[str, Any]], CouncilEntryProposal | None]


class CouncilAuthorizedPaperLoop(AutonomousPaperLoop):
    """Autonomous paper loop whose new entries require council authorization."""

    def __init__(
        self,
        stream,
        *,
        decision_runtime: CanonicalPaperDecisionRuntime,
        proposal_provider: ProposalProvider,
        database=None,
    ) -> None:
        super().__init__(stream, database=database or decision_runtime.database)
        if decision_runtime.database.dsn != self.database.dsn:
            raise ValueError("paper loop and decision runtime must use the same database")
        self.decision_runtime = decision_runtime
        self.proposal_provider = proposal_provider
        self._pending_authorization: PaperDecisionAuthorization | None = None
        self._pending_exit_context: dict[str, str] | None = None
        self._state["peak_equity"] = max(
            float(self._state.get("peak_equity", 0.0) or 0.0),
            float(self._state.get("equity", 0.0) or 0.0),
        )

    def tick(self) -> None:
        market = self.stream.snapshot()
        if not market.get("verified"):
            self._event("BLOCK", "Market stream is unavailable or stale; no paper order created")
            return

        with self._lock:
            for symbol in self.stream.symbols:
                try:
                    quote = self.stream.quote(symbol)
                except Exception as exc:
                    self._event("BLOCK", f"verified_quote_error:{type(exc).__name__}: {exc}", symbol)
                    continue

                position = self._state["positions"].get(symbol)
                if position:
                    self._manage_protective_exit(symbol, quote)
                    continue

                try:
                    proposal = self.proposal_provider(
                        symbol,
                        quote,
                        self._proposal_state_snapshot(),
                    )
                except Exception as exc:
                    self._event("BLOCK", f"proposal_provider_error:{type(exc).__name__}: {exc}", symbol)
                    continue

                if proposal is None:
                    self._event("WAIT", "no fresh canonical council proposal", symbol)
                    continue

                try:
                    authorization = self.decision_runtime.assess_entry(
                        proposal.decision_id,
                        proposal.agent_payloads,
                        proposal.evidence_packet,
                        general_controller_decision=proposal.general_controller_decision,
                        now_ms=self._now_ms(),
                        regime=proposal.regime,
                    )
                except Exception as exc:
                    self._event("BLOCK", f"canonical_decision_error:{type(exc).__name__}: {exc}", symbol)
                    continue

                if not authorization.authorized:
                    action = "BLOCK" if authorization.decision is TradingDecision.BLOCK else "WAIT"
                    self._event(action, authorization.reason, symbol)
                    continue

                if authorization.candidate_result.candidate.symbol != symbol:
                    self._event("BLOCK", "authorized candidate symbol does not match loop symbol", symbol)
                    continue

                if authorization.candidate_result.candidate.side.value != "Buy":
                    self._event("WAIT", "spot paper loop does not open a short position", symbol)
                    continue

                try:
                    self.decision_runtime.consume_authorization(
                        authorization,
                        consumed_at_ms=self._now_ms(),
                    )
                except Exception as exc:
                    self._event("BLOCK", f"authorization_consumption_error:{type(exc).__name__}: {exc}", symbol)
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
                        self._event("BLOCK", "authorized entry could not allocate a safe paper budget", symbol)
                        continue
                    position["decision_id"] = authorization.decision_id
                    position["candidate_id"] = authorization.candidate_result.candidate.candidate_id
                    position["evidence_class"] = "verified_market"
                    position["verified_market_data"] = True
                    position["regime"] = authorization.assessment.regime
                finally:
                    self._pending_authorization = None

            self._mark_to_market(market)
            self._state["peak_equity"] = max(
                float(self._state.get("peak_equity", 0.0) or 0.0),
                float(self._state.get("equity", 0.0) or 0.0),
            )
            self._persist()

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

    def _close(self, symbol: str, price: float, reason: str) -> None:
        position = dict(self._state["positions"].get(symbol) or {})
        self._pending_exit_context = {
            "decision_id": str(position.get("decision_id") or "").strip(),
            "candidate_id": str(position.get("candidate_id") or "").strip(),
        }
        try:
            super()._close(symbol, price, reason)
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
                net = float(net_pnl or 0.0)
                try:
                    settlement = self.decision_runtime.settle_exit(
                        decision_id,
                        net_pnl=net,
                        drawdown_contribution=max(0.0, -net),
                    )
                    item["decision_settlement"] = settlement
                    item["reputation_recorded"] = bool(settlement.get("reputation_recorded"))
                except Exception as exc:
                    item["decision_settlement_error"] = f"{type(exc).__name__}: {exc}"

        self._state["trades"].append(item)
        self._state["trades"] = self._state["trades"][-500:]
        self._event(side, reason, symbol)

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
        state["decision_mode"] = "CANONICAL_COUNCIL_REQUIRED"
        state["entry_without_authorization_allowed"] = False
        state["protective_exit_without_new_council_allowed"] = True
        state["authorization_single_use"] = True
        state["verified_exit_learning"] = True
        state["decision_runtime"] = self.decision_runtime.status()
        return state


__all__ = ["CouncilAuthorizedPaperLoop", "CouncilEntryProposal", "ProposalProvider"]
