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

    def tick(self) -> None:
        market = self.stream.snapshot()
        if not market.get("verified"):
            self._event("BLOCK", "Market stream is unavailable or stale; no paper order created")
            return

        with self._lock:
            for symbol in self.stream.symbols:
                try:
                    quote = self.stream.quote(symbol)
                except RuntimeError as exc:
                    self._event("BLOCK", str(exc), symbol)
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
                    self._event("WAIT", "no canonical council proposal", symbol)
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

                if authorization.candidate_result.candidate.side.value != "BUY":
                    self._event("WAIT", "spot paper loop does not open a short position", symbol)
                    continue

                self._pending_authorization = authorization
                try:
                    self._open(
                        symbol,
                        quote.price,
                        f"canonical_council_allow:{authorization.decision_id}",
                    )
                    position = self._state["positions"].get(symbol)
                    if position is not None:
                        position["decision_id"] = authorization.decision_id
                        position["candidate_id"] = authorization.candidate_result.candidate.candidate_id
                        position["evidence_class"] = "verified_market"
                        position["verified_market_data"] = True
                finally:
                    self._pending_authorization = None

            self._mark_to_market(market)
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
        super()._trade(symbol, side, quantity, price, fee, reason, net_pnl)
        if side != "BUY" or self._pending_authorization is None or not self._state["trades"]:
            return
        authorization = self._pending_authorization
        trade = self._state["trades"][-1]
        trade.update(
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
            }
        )

    def _proposal_state_snapshot(self) -> dict[str, Any]:
        return {
            "cash": float(self._state.get("cash", 0.0)),
            "equity": float(self._state.get("equity", 0.0)),
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
        state["decision_runtime"] = self.decision_runtime.status()
        return state


__all__ = ["CouncilAuthorizedPaperLoop", "CouncilEntryProposal", "ProposalProvider"]
