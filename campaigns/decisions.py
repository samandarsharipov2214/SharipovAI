"""Immutable manual decisions for completed Testnet campaign reports.

A decision is evidence only. It cannot modify execution flags, deployment,
strategy leadership, credentials, capital or Mainnet availability.
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Mapping

from storage import ProjectDatabase, VersionConflict

from .core import FinalPromotionReportEngine, TestnetShadowCampaign

_NAMESPACE = "campaign_promotion_decisions"
_EVENT_NAMESPACE = "campaign_promotion_decision_events"


class CampaignPromotionDecisionEngine:
    """Validate and persist one owner decision per immutable final report."""

    def __init__(
        self,
        database: ProjectDatabase | None = None,
        *,
        campaigns: TestnetShadowCampaign | None = None,
        reports: FinalPromotionReportEngine | None = None,
    ) -> None:
        self.database = database or ProjectDatabase()
        self.database.initialize()
        self.campaigns = campaigns or TestnetShadowCampaign(self.database)
        self.reports = reports or FinalPromotionReportEngine(self.database)

    def snapshot(self, campaign_id: str) -> dict[str, Any]:
        campaign = self._campaign(campaign_id)
        report_id = str(campaign.get("final_report_id") or "")
        report = self.reports.get(report_id) if report_id else None
        current = self.database.get_json(_NAMESPACE, str(campaign["campaign_id"]))
        decision = dict(current["value"]) if current else {}
        return {
            "status": "decided" if decision else "awaiting_manual_decision" if report else "report_pending",
            "campaign_id": campaign["campaign_id"],
            "experiment_id": campaign["experiment_id"],
            "scope": campaign["scope"],
            "campaign_status": campaign["status"],
            "report_id": report_id,
            "report_status": str((report or {}).get("status", "pending")),
            "eligible_for_approval": bool(
                report
                and report.get("eligible_for_manual_decision")
                and not report.get("failed_campaign_gates")
            ),
            "decision": decision,
            "approval_token": self.token(campaign["campaign_id"], report_id, approve=True) if report_id else "",
            "rejection_token": self.token(campaign["campaign_id"], report_id, approve=False) if report_id else "",
            "runtime_flags_changed": False,
            "runtime_deployment_changed": False,
            "mainnet_enabled": False,
        }

    def decide(
        self,
        campaign_id: str,
        *,
        approve: bool,
        actor: str,
        reason: str,
        approval_token: str,
        now_ms: int | None = None,
    ) -> dict[str, Any]:
        campaign = self._campaign(campaign_id)
        if str(campaign.get("status")) != "completed":
            raise ValueError("manual campaign decision requires a completed campaign")
        report_id = str(campaign.get("final_report_id") or "")
        if not report_id:
            raise ValueError("manual campaign decision requires an immutable final report")
        report = self.reports.get(report_id)
        if report is None:
            raise RuntimeError("campaign final report reference is missing")
        expected_token = self.token(str(campaign["campaign_id"]), report_id, approve=approve)
        if approval_token != expected_token:
            raise ValueError("campaign decision token does not match campaign/report/action")
        if approve:
            if str(report.get("status")) != "eligible_for_manual_decision":
                raise ValueError("blocked final report cannot be approved")
            if not bool(report.get("eligible_for_manual_decision")):
                raise ValueError("final report is not eligible for manual approval")
            if report.get("failed_campaign_gates"):
                raise ValueError("final report contains failed campaign gates")

        clean_actor = _identifier(actor, "actor")
        clean_reason = _text(reason, "reason")
        timestamp = _timestamp(now_ms)
        evidence_sha = str(report.get("evidence_sha256") or "")
        if len(evidence_sha) != 64:
            raise ValueError("final report evidence SHA-256 is missing")
        payload = {
            "decision_id": "campaign_decision_" + _digest(
                {
                    "campaign_id": campaign["campaign_id"],
                    "report_id": report_id,
                    "approved": bool(approve),
                    "actor": clean_actor,
                    "reason": clean_reason,
                    "evidence_sha256": evidence_sha,
                }
            )[:32],
            "campaign_id": campaign["campaign_id"],
            "experiment_id": campaign["experiment_id"],
            "scope": campaign["scope"],
            "report_id": report_id,
            "report_status": report.get("status"),
            "approved": bool(approve),
            "status": "approved" if approve else "rejected",
            "actor": clean_actor,
            "reason": clean_reason,
            "evidence_sha256": evidence_sha,
            "decided_at_ms": timestamp,
            "manual_decision_only": True,
            "runtime_flags_changed": False,
            "runtime_deployment_changed": False,
            "mainnet_enabled": False,
        }
        key = str(campaign["campaign_id"])
        try:
            version = self.database.put_json(_NAMESPACE, key, payload, expected_version=0)
        except VersionConflict:
            existing = self.database.get_json(_NAMESPACE, key)
            if existing is None:
                raise
            if _decision_identity(existing["value"]) != _decision_identity(payload):
                raise ValueError("campaign already has a different immutable manual decision")
            return {**dict(existing["value"]), "version": int(existing["version"]), "idempotent": True}
        event_id = self.database.append_event(
            _EVENT_NAMESPACE,
            "campaign",
            key,
            {
                "action": "approved" if approve else "rejected",
                "decision_id": payload["decision_id"],
                "report_id": report_id,
                "actor": clean_actor,
                "reason": clean_reason,
                "evidence_sha256": evidence_sha,
            },
            created_at_ms=timestamp,
        )
        return {**payload, "version": version, "event_id": event_id, "idempotent": False}

    @staticmethod
    def token(campaign_id: str, report_id: str, *, approve: bool) -> str:
        action = "APPROVE" if approve else "REJECT"
        return f"CAMPAIGN_DECISION:{campaign_id}:{report_id}:{action}"

    def _campaign(self, campaign_id: str) -> dict[str, Any]:
        clean = _identifier(campaign_id, "campaign_id")
        campaign = self.campaigns.get(clean)
        if campaign is None:
            raise KeyError(clean)
        return campaign


def _decision_identity(value: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        value.get("campaign_id"),
        value.get("report_id"),
        bool(value.get("approved")),
        value.get("actor"),
        value.get("reason"),
        value.get("evidence_sha256"),
    )


def _identifier(value: Any, name: str) -> str:
    clean = str(value or "").strip()
    if not clean or len(clean) > 200 or any(
        character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.:-"
        for character in clean
    ):
        raise ValueError(f"invalid {name}")
    return clean


def _text(value: Any, name: str) -> str:
    clean = str(value or "").strip()
    if not clean or len(clean) > 4_000:
        raise ValueError(f"invalid {name}")
    return clean


def _timestamp(value: int | None) -> int:
    parsed = int(time.time() * 1000) if value is None else int(value)
    if parsed <= 0:
        raise ValueError("timestamp must be positive")
    return parsed


def _digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = ["CampaignPromotionDecisionEngine"]
