from __future__ import annotations

import pytest

from campaigns.decisions import CampaignPromotionDecisionEngine
from storage import ProjectDatabase


class Campaigns:
    def __init__(self, *, status: str = "completed", report_id: str = "report_phase7") -> None:
        self.status = status
        self.report_id = report_id

    def get(self, campaign_id: str):
        if campaign_id != "campaign_phase7":
            return None
        return {
            "campaign_id": campaign_id,
            "experiment_id": "experiment_phase7",
            "scope": "BTCUSDT",
            "status": self.status,
            "final_report_id": self.report_id,
        }


class Reports:
    def __init__(self, *, eligible: bool = True) -> None:
        self.eligible = eligible

    def get(self, report_id: str):
        if report_id != "report_phase7":
            return None
        return {
            "report_id": report_id,
            "status": "eligible_for_manual_decision" if self.eligible else "blocked",
            "eligible_for_manual_decision": self.eligible,
            "failed_campaign_gates": [] if self.eligible else ["zero_orphans"],
            "evidence_sha256": "a" * 64,
        }


def engine(tmp_path, *, status: str = "completed", eligible: bool = True):
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'decisions.db'}")
    database.initialize()
    return CampaignPromotionDecisionEngine(
        database,
        campaigns=Campaigns(status=status),
        reports=Reports(eligible=eligible),
    )


def test_snapshot_exposes_exact_approval_and_rejection_tokens(tmp_path) -> None:
    service = engine(tmp_path)
    snapshot = service.snapshot("campaign_phase7")

    assert snapshot["status"] == "awaiting_manual_decision"
    assert snapshot["eligible_for_approval"] is True
    assert snapshot["approval_token"] == (
        "CAMPAIGN_DECISION:campaign_phase7:report_phase7:APPROVE"
    )
    assert snapshot["rejection_token"] == (
        "CAMPAIGN_DECISION:campaign_phase7:report_phase7:REJECT"
    )
    assert snapshot["mainnet_enabled"] is False


def test_approval_is_immutable_and_idempotent(tmp_path) -> None:
    service = engine(tmp_path)
    token = service.token("campaign_phase7", "report_phase7", approve=True)

    first = service.decide(
        "campaign_phase7",
        approve=True,
        actor="owner",
        reason="Twenty actual matched fills and all identity gates are green.",
        approval_token=token,
        now_ms=1_800_000_000_000,
    )
    second = service.decide(
        "campaign_phase7",
        approve=True,
        actor="owner",
        reason="Twenty actual matched fills and all identity gates are green.",
        approval_token=token,
        now_ms=1_800_000_000_001,
    )

    assert first["status"] == "approved"
    assert first["runtime_flags_changed"] is False
    assert first["runtime_deployment_changed"] is False
    assert first["mainnet_enabled"] is False
    assert second["idempotent"] is True
    assert second["decision_id"] == first["decision_id"]


def test_conflicting_second_decision_is_rejected(tmp_path) -> None:
    service = engine(tmp_path)
    approve_token = service.token("campaign_phase7", "report_phase7", approve=True)
    reject_token = service.token("campaign_phase7", "report_phase7", approve=False)
    service.decide(
        "campaign_phase7",
        approve=True,
        actor="owner",
        reason="Approved from verified evidence.",
        approval_token=approve_token,
    )

    with pytest.raises(ValueError, match="different immutable manual decision"):
        service.decide(
            "campaign_phase7",
            approve=False,
            actor="owner",
            reason="Changed my mind without new campaign evidence.",
            approval_token=reject_token,
        )


def test_blocked_report_cannot_be_approved(tmp_path) -> None:
    service = engine(tmp_path, eligible=False)
    token = service.token("campaign_phase7", "report_phase7", approve=True)

    with pytest.raises(ValueError, match="blocked final report"):
        service.decide(
            "campaign_phase7",
            approve=True,
            actor="owner",
            reason="Attempt to override a failed automated gate.",
            approval_token=token,
        )


def test_incomplete_campaign_cannot_be_decided(tmp_path) -> None:
    service = engine(tmp_path, status="running")
    token = service.token("campaign_phase7", "report_phase7", approve=False)

    with pytest.raises(ValueError, match="completed campaign"):
        service.decide(
            "campaign_phase7",
            approve=False,
            actor="owner",
            reason="Campaign is not complete.",
            approval_token=token,
        )
