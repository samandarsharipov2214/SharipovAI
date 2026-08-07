"""Operator-transparent wrapper for the canonical autonomous council provider.

This wrapper does not change any trading threshold, vote rule, risk policy, or
execution authority. It only records why the existing provider returned a
proposal or WAITed before one could be formed.
"""
from __future__ import annotations

import math
import time
from collections.abc import Mapping
from typing import Any

from trading_candidate import TradingDecision

from .council_provider import AutonomousCouncilProposalProvider as _BaseProvider
from .decision_trace import persist_decision_trace, read_decision_trace

_NEWS_AGENTS = {"crypto_ai", "finance_ai", "economy_ai", "security_ai", "world_ai"}
_REQUIRED_CONSENSUS_SOURCES = 3
_MAX_QUOTE_AGE_MS = 2_000


class AutonomousCouncilProposalProvider(_BaseProvider):
    """Canonical provider plus bounded per-symbol operator trace."""

    def __call__(self, symbol: str, quote: Any, state: Mapping[str, Any]):
        proposal = super().__call__(symbol, quote, state)
        clean_symbol = _symbol(symbol)
        now_ms = int(time.time() * 1000)
        if proposal is None:
            self._record_wait(clean_symbol, quote, state, now_ms=now_ms)
            return None

        opinions = [dict(item) for item in proposal.agent_payloads if isinstance(item, Mapping)]
        counts = _vote_counts(opinions)
        news = [item for item in opinions if str(item.get("agent_id") or "") in _NEWS_AGENTS]
        risk_blocks = list(proposal.evidence_packet.risk_blocks)
        directive = proposal.general_controller_decision
        market_action = _market_action(opinions)
        reason = _directive_reason(
            directive,
            market_action=market_action,
            vote_counts=counts,
            news_actions=[str(item.get("action") or "WAIT").upper() for item in news],
            risk_blocks=risk_blocks,
            cash=_finite_or_none(state.get("cash")),
            entry_threshold=self.entry_change_percent,
        )
        market = self.stream.evidence(clean_symbol)
        sources = _sources(market)
        quote_ts = int(getattr(quote, "received_at_unix_ms", 0) or 0)
        persist_decision_trace(
            self.database,
            clean_symbol,
            {
                "status": "BLOCK" if directive is TradingDecision.BLOCK else "PROPOSAL",
                "phase": "council",
                "reason": reason,
                "decision_id": proposal.decision_id,
                "market_verified": market.get("verified") is True,
                "synthetic_fallback_used": market.get("synthetic_fallback_used") is True,
                "consensus_source_count": len(sources),
                "required_consensus_source_count": _REQUIRED_CONSENSUS_SOURCES,
                "quote_age_ms": max(0, now_ms - quote_ts) if quote_ts > 0 else None,
                "quote_max_age_ms": _MAX_QUOTE_AGE_MS,
                "change_24h_percent": _finite_or_none(getattr(quote, "change_24h_percent", None)),
                "entry_change_percent": self.entry_change_percent,
                "turnover_usdt": _finite_or_none(getattr(quote, "volume_24h", None)),
                "min_turnover_usdt": self.min_turnover_usdt,
                "market_action": market_action,
                "fresh_news_opinion_count": len(news),
                "news_actions": [str(item.get("action") or "WAIT").upper() for item in news],
                "vote_counts": counts,
                "risk_blocks": risk_blocks,
                "general_controller_decision": directive.value,
                "cash": _finite_or_none(state.get("cash")),
            },
            now_ms=now_ms,
        )
        return proposal

    def decision_trace(self, symbol: str) -> dict[str, Any] | None:
        return read_decision_trace(self.database, symbol)

    def _record_wait(self, symbol: str, quote: Any, state: Mapping[str, Any], *, now_ms: int) -> None:
        last = self.database.get_json("autonomous_council_runtime", symbol)
        generated = 0
        if isinstance(last, dict) and isinstance(last.get("value"), dict):
            generated = int(last["value"].get("last_generated_at_ms") or 0)
        if generated > 0 and now_ms - generated < self.proposal_interval_ms:
            persist_decision_trace(
                self.database,
                symbol,
                {
                    "status": "WAIT",
                    "phase": "proposal_interval",
                    "reason": "waiting for the next canonical council proposal interval",
                    "proposal_interval_ms": self.proposal_interval_ms,
                    "next_proposal_in_ms": max(0, self.proposal_interval_ms - (now_ms - generated)),
                },
                now_ms=now_ms,
            )
            return

        try:
            market = self.stream.evidence(symbol)
        except Exception as exc:
            persist_decision_trace(
                self.database,
                symbol,
                {
                    "status": "BLOCK",
                    "phase": "market_evidence",
                    "reason": f"market evidence unavailable: {type(exc).__name__}",
                    "market_verified": False,
                },
                now_ms=now_ms,
            )
            return

        verified = market.get("verified") is True
        synthetic = market.get("synthetic_fallback_used") is True
        sources = _sources(market)
        change = _finite_or_none(getattr(quote, "change_24h_percent", None))
        turnover = _finite_or_none(getattr(quote, "volume_24h", None))
        quote_ts = int(getattr(quote, "received_at_unix_ms", 0) or 0)
        quote_age = max(0, now_ms - quote_ts) if quote_ts > 0 else None
        base = {
            "status": "WAIT",
            "phase": "preflight",
            "market_verified": verified,
            "synthetic_fallback_used": synthetic,
            "consensus_source_count": len(sources),
            "required_consensus_source_count": _REQUIRED_CONSENSUS_SOURCES,
            "quote_age_ms": quote_age,
            "quote_max_age_ms": _MAX_QUOTE_AGE_MS,
            "change_24h_percent": change,
            "entry_change_percent": self.entry_change_percent,
            "turnover_usdt": turnover,
            "min_turnover_usdt": self.min_turnover_usdt,
            "cash": _finite_or_none(state.get("cash")),
        }
        if not verified or synthetic:
            base.update(status="BLOCK", phase="market_verification", reason="verified non-synthetic market evidence is required")
        elif len(sources) < _REQUIRED_CONSENSUS_SOURCES:
            base.update(reason=f"cross-exchange consensus requires {_REQUIRED_CONSENSUS_SOURCES} sources; got {len(sources)}")
        elif change is None or turnover is None or turnover < 0:
            base.update(reason="quote change/turnover evidence is incomplete")
        elif quote_ts <= 0 or quote_age is None or quote_age > _MAX_QUOTE_AGE_MS:
            base.update(reason=f"verified quote is stale; max age is {_MAX_QUOTE_AGE_MS} ms")
        else:
            market_action = _direction(change, self.entry_change_percent)
            base["market_action"] = market_action
            if market_action == "WAIT":
                base["reason"] = f"24h change {change:.4f}% is inside ±{self.entry_change_percent:.4f}% entry threshold"
            elif turnover < self.min_turnover_usdt:
                base["reason"] = f"turnover {turnover:.2f} USDT is below {self.min_turnover_usdt:.2f} USDT minimum"
            else:
                base["reason"] = "canonical council did not produce an eligible proposal after preflight"
        persist_decision_trace(self.database, symbol, base, now_ms=now_ms)


def _sources(market: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(item) for item in market.get("consensus_sources", ()) if str(item).strip()))


def _vote_counts(opinions: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"BUY": 0, "SELL": 0, "WAIT": 0, "BLOCK": 0}
    for item in opinions:
        action = str(item.get("action") or "WAIT").upper()
        counts[action if action in counts else "WAIT"] += 1
    return counts


def _market_action(opinions: list[dict[str, Any]]) -> str:
    for item in opinions:
        if str(item.get("agent_id") or "") == "market_intelligence":
            return str(item.get("action") or "WAIT").upper()
    return "WAIT"


def _directive_reason(
    directive: TradingDecision,
    *,
    market_action: str,
    vote_counts: Mapping[str, int],
    news_actions: list[str],
    risk_blocks: list[str],
    cash: float | None,
    entry_threshold: float,
) -> str:
    if directive is TradingDecision.BLOCK:
        return "; ".join(risk_blocks) or "canonical Risk Engine blocked the proposal"
    if directive is TradingDecision.ALLOW:
        return "council preflight passed; proposal is pending canonical Decision Quality authorization"
    if market_action == "WAIT":
        return f"market direction is inside ±{entry_threshold:.4f}% entry threshold"
    if int(vote_counts.get("SELL", 0)) > 0:
        return "one or more eligible agents voted SELL; controller requires no SELL votes for spot entry"
    if "BUY" not in news_actions:
        return "no fresh News Intelligence opinion voted BUY"
    if int(vote_counts.get("BUY", 0)) < 4:
        return f"controller requires at least 4 BUY votes; got {int(vote_counts.get('BUY', 0))}"
    if cash is None or cash <= 0:
        return "paper cash is not available for a new entry"
    return "general controller returned WAIT"


def _direction(change: float, threshold: float) -> str:
    if change >= threshold:
        return "BUY"
    if change <= -threshold:
        return "SELL"
    return "WAIT"


def _finite_or_none(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


__all__ = ["AutonomousCouncilProposalProvider"]
