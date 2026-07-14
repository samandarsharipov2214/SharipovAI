"""Shadow-only Testnet bridge using actual Bybit filters and campaign evidence."""
from __future__ import annotations

import time
from typing import Any, Mapping

from exchange_connector.execution_contract import build_execution_request
from trading_candidate import validate_trading_candidate

from .shadow_mode import ShadowModePlanner
from .testnet_bridge import AutonomousTestnetBridge, _candidate_from_trade, _positive_number

_FINAL_RECORD_STATUSES = {
    "accepted",
    "unresolved",
    "invalid",
    "ignored_disabled",
    "ignored_stage",
    "ignored_non_trade",
    "ignored_campaign",
}
_ACTIVE_NAMESPACE = "scheduled_campaign_active"
_CAMPAIGN_NAMESPACE = "testnet_shadow_campaigns"


class ShadowModeTestnetBridge(AutonomousTestnetBridge):
    """Mirror one Paper candidate into a tiny, rule-normalized Testnet order."""

    def __init__(self, *args: Any, shadow_planner: ShadowModePlanner | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.shadow_planner = shadow_planner or ShadowModePlanner()

    def snapshot(self) -> dict[str, Any]:
        campaign = self._active_campaign(int(time.time() * 1000), required=False)
        return {
            **super().snapshot(),
            "shadow_mode": True,
            "shadow_max_notional_usdt": self.shadow_planner.policy.maximum_testnet_notional_usdt,
            "dynamic_bybit_reference_required": True,
            "paper_sizing_changed": False,
            "active_campaign": campaign or {},
        }

    def tick(self) -> None:
        trades = self._paper_trades()
        if not self.enabled():
            self._baseline(trades, "ignored_disabled", "disabled")
            return
        if not self._ensure_reconciled():
            return

        assessment = self.stages.assess()
        if assessment.eligible_stage < 3:
            self._baseline(trades, "ignored_stage", "blocked_by_stage_evidence")
            return

        for trade in trades:
            trade_id = str(trade.get("trade_id", "")).strip()
            if not trade_id:
                raise RuntimeError("paper trade has no stable trade_id")
            existing = self.database.get_json(self.record_namespace, trade_id)
            if existing is not None:
                status = str(existing["value"].get("status", ""))
                if status not in _FINAL_RECORD_STATUSES:
                    raise RuntimeError(f"unknown persisted bridge status for {trade_id}: {status}")
                continue

            if trade.get("side") not in {"BUY", "SELL"}:
                self._record(
                    trade_id,
                    "ignored_non_trade",
                    trade,
                    message="Paper record is not an executable BUY/SELL trade",
                )
                continue

            now_ms = int(time.time() * 1000)
            campaign = self._active_campaign(now_ms, required=False)
            if campaign is not None:
                created_at_ms = int(trade.get("created_at_ms") or 0)
                if created_at_ms < self._campaign_started_at(campaign):
                    self._record(
                        trade_id,
                        "ignored_campaign",
                        trade,
                        message="paper trade predates active scheduled campaign",
                        campaign_id=campaign["campaign_id"],
                        experiment_id=campaign["experiment_id"],
                        scope=campaign["scope"],
                    )
                    continue

            try:
                paper_quantity = _positive_number(trade.get("quantity"), "paper quantity")
                candidate = _candidate_from_trade(trade, database=self.database, now_ms=now_ms)
                validation = validate_trading_candidate(
                    candidate,
                    now_ms=now_ms,
                    max_market_age_ms=self.shadow_planner.policy.maximum_trade_age_ms,
                )
                plan = self.shadow_planner.plan(
                    paper_trade=trade,
                    testnet_candidate=candidate,
                    execution_max_notional=self.client.max_notional,
                    now_ms=now_ms,
                )
                if campaign is not None:
                    minimum = float(campaign["minimum_notional_usdt"])
                    maximum = float(campaign["maximum_notional_usdt"])
                    if not minimum <= plan.testnet_notional <= maximum:
                        raise ValueError(
                            f"campaign Testnet notional must be within {minimum:.2f}..{maximum:.2f} USDT"
                        )
                request = build_execution_request(
                    candidate,
                    validation,
                    quantity=plan.testnet_quantity,
                    now_ms=now_ms,
                )
            except Exception as exc:
                message = f"{type(exc).__name__}: {exc}"
                context = _campaign_context(campaign)
                self.journal.append(
                    {
                        "journal_event_id": f"shadow_invalid_{trade_id}",
                        "status": "blocked_or_error",
                        "mode": self.client.mode,
                        "environment": "testnet",
                        "category": "spot",
                        "symbol": trade.get("symbol"),
                        "side": trade.get("side"),
                        "quantity": trade.get("quantity"),
                        "paper_trade_id": trade_id,
                        "message": message,
                        "origin": "shadow_testnet_bridge",
                        **context,
                    }
                )
                self._record(trade_id, "invalid", trade, message=message, **context)
                self._set_state("skipped_invalid_shadow_trade", message, trade_id=trade_id)
                continue

            context = _campaign_context(campaign)
            try:
                result = self.client.execute(request, now_ms=now_ms)
            except Exception as exc:
                message = f"{type(exc).__name__}: {exc}"
                self.journal.append(
                    {
                        "journal_event_id": f"shadow_unresolved_{trade_id}",
                        "status": "unresolved",
                        "mode": self.client.mode,
                        "environment": "testnet",
                        "category": request.category.value,
                        "symbol": request.symbol,
                        "side": request.side.value,
                        "quantity": request.quantity,
                        "candidate_id": request.candidate_id,
                        "source_candidate_id": plan.source_candidate_id,
                        "shadow_pair_id": plan.shadow_pair_id,
                        "order_link_id": request.order_link_id,
                        "paper_trade_id": trade_id,
                        "message": message,
                        "origin": "shadow_testnet_bridge",
                        "requires_reconciliation": True,
                        **context,
                    }
                )
                self._record(
                    trade_id,
                    "unresolved",
                    trade,
                    message=message,
                    paper_quantity=paper_quantity,
                    mirrored_quantity=request.quantity,
                    testnet_notional=plan.testnet_notional,
                    candidate_id=request.candidate_id,
                    source_candidate_id=plan.source_candidate_id,
                    shadow_pair_id=plan.shadow_pair_id,
                    order_link_id=request.order_link_id,
                    trading_reference=plan.to_dict(),
                    **context,
                )
                self._set_state("unresolved", message, trade_id=trade_id)
                self._reconciliation_report = {
                    "status": "blocked",
                    "restart_safe": False,
                    "errors": [message],
                    "unresolved_order_link_ids": [request.order_link_id],
                }
                break

            journal_item = self.journal.append(
                {
                    **result.to_dict(),
                    "journal_event_id": f"shadow_accepted_{trade_id}",
                    "environment": "testnet",
                    "category": request.category.value,
                    "candidate_hash": request.candidate_hash,
                    "source_candidate_id": plan.source_candidate_id,
                    "shadow_pair_id": plan.shadow_pair_id,
                    "paper_trade_id": trade_id,
                    "paper_quantity": paper_quantity,
                    "mirrored_quantity": request.quantity,
                    "testnet_notional": plan.testnet_notional,
                    "taker_fee_rate": plan.taker_fee_rate,
                    "quantity_step": plan.quantity_step,
                    "minimum_notional": plan.minimum_notional,
                    "signal_reason": trade.get("reason"),
                    "origin": "shadow_testnet_bridge",
                    **context,
                }
            )
            self._record(
                trade_id,
                "accepted",
                trade,
                message=str(result.message),
                paper_quantity=paper_quantity,
                mirrored_quantity=request.quantity,
                testnet_notional=plan.testnet_notional,
                order_id=result.order_id,
                candidate_id=request.candidate_id,
                source_candidate_id=plan.source_candidate_id,
                shadow_pair_id=plan.shadow_pair_id,
                order_link_id=request.order_link_id,
                journal_event_id=journal_item["journal_event_id"],
                trading_reference=plan.to_dict(),
                **context,
            )
            self._set_state("accepted_shadow", "", trade_id=trade_id, order_id=result.order_id)

    def _active_campaign(self, now_ms: int, *, required: bool) -> dict[str, Any] | None:
        current = self.database.get_json(_ACTIVE_NAMESPACE, "current")
        if current is None:
            if required:
                raise RuntimeError("scheduled campaign authorization is missing")
            return None
        value = current.get("value")
        if not isinstance(value, Mapping):
            raise RuntimeError("scheduled campaign authorization is malformed")
        if str(value.get("status")) != "active" or int(value.get("expires_at_ms") or 0) < now_ms:
            if required:
                raise RuntimeError("scheduled campaign authorization is inactive or expired")
            return None
        for name in ("campaign_id", "experiment_id", "scope"):
            if not str(value.get(name) or "").strip():
                raise RuntimeError(f"scheduled campaign authorization missing {name}")
        return dict(value)

    def _campaign_started_at(self, campaign: Mapping[str, Any]) -> int:
        identifier = str(campaign.get("campaign_id") or "").strip()
        current = self.database.get_json(_CAMPAIGN_NAMESPACE, identifier) if identifier else None
        if current is not None and isinstance(current.get("value"), Mapping):
            started = int(current["value"].get("started_at_ms") or 0)
            if started > 0:
                return started
        activated = int(campaign.get("activated_at_ms") or 0)
        if activated <= 0:
            raise RuntimeError("scheduled campaign activation timestamp is invalid")
        return activated


def _campaign_context(campaign: Mapping[str, Any] | None) -> dict[str, Any]:
    if campaign is None:
        return {"campaign_id": "", "experiment_id": "", "scope": ""}
    return {
        "campaign_id": str(campaign["campaign_id"]),
        "experiment_id": str(campaign["experiment_id"]),
        "scope": str(campaign["scope"]),
    }


__all__ = ["ShadowModeTestnetBridge"]
