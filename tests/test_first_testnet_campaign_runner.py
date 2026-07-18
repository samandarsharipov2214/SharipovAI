from __future__ import annotations

import argparse
import json
from types import SimpleNamespace

from scripts.first_testnet_campaign import run
from scripts.testnet_campaignctl import CYCLE_CONFIRMATION, REPORT_CONFIRMATION, START_CONFIRMATION


class FakeCampaign:
    def __init__(self, rows):
        self.rows = list(rows)
        self.calls = 0

    def get(self, campaign_id):
        for row in self.rows:
            if row.get("campaign_id") == campaign_id:
                return dict(row)
        return None

    def run_cycle(self, campaign_id, *, actor):
        del actor
        self.calls += 1
        row = dict(self.rows[min(self.calls, len(self.rows) - 1)])
        assert row["campaign_id"] == campaign_id
        return row


class FakeOperations:
    def __init__(self, plan, started):
        self.plan = dict(plan)
        self.started = dict(started)
        self.start_calls = 0

    def first_testnet_plan(self, **kwargs):
        del kwargs
        return dict(self.plan)

    def start_first_testnet_campaign(self, **kwargs):
        del kwargs
        self.start_calls += 1
        return {"campaign": dict(self.started)}

    def snapshot(self):
        return {"status": "ok", "mainnet_enabled": False}


class FakeReports:
    def generate(self, campaign_id, *, actor):
        del actor
        return {"report_id": f"report_{campaign_id}", "eligible_for_manual_decision": True, "mainnet_enabled": False}


def _args(tmp_path, **overrides):
    values = {
        "experiment_id": "experiment_1",
        "scope": "BTCUSDT",
        "actor": "operator",
        "resume_campaign_id": "",
        "max_cycles": 4,
        "interval_seconds": 1.0,
        "timeout_seconds": 60,
        "output_dir": str(tmp_path),
        "start_confirmation": START_CONFIRMATION,
        "cycle_confirmation": CYCLE_CONFIRMATION,
        "report_confirmation": REPORT_CONFIRMATION,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _completed(campaign_id="campaign_1"):
    return {
        "campaign_id": campaign_id,
        "experiment_id": "experiment_1",
        "scope": "BTCUSDT",
        "status": "completed",
        "metrics": {
            "matched_fill_count": 20,
            "actual_execution_fees": True,
            "unmatched_paper_count": 0,
            "unmatched_testnet_count": 0,
            "orphan_execution_count": 0,
            "duplicate_order_count": 0,
            "unresolved_order_count": 0,
        },
        "failed_gates": [],
    }


def test_runner_collects_terminal_real_fill_evidence_bundle(tmp_path) -> None:
    running = {
        "campaign_id": "campaign_1",
        "experiment_id": "experiment_1",
        "scope": "BTCUSDT",
        "status": "running",
        "metrics": {"matched_fill_count": 12},
        "failed_gates": ["minimum_20_matched_fills_pending"],
    }
    operations = FakeOperations({"can_start": True, "blockers": []}, running)
    services = SimpleNamespace(operations=operations, campaign=FakeCampaign([running, _completed()]), reports=FakeReports())
    result = run(_args(tmp_path), services, sleep=lambda _: None, monotonic=lambda: 0.0)
    assert result["real_fill_evidence_confirmed"] is True
    assert result["matched_fill_count"] == 20
    assert result["mainnet_enabled"] is False
    evidence = tmp_path / "campaign_1"
    assert (evidence / "cycles.jsonl").exists()
    assert (evidence / "final-promotion-report.json").exists()
    persisted = json.loads((evidence / "runner-result.json").read_text(encoding="utf-8"))
    assert persisted["real_fill_evidence_confirmed"] is True


def test_runner_blocks_launch_and_preserves_plan_evidence(tmp_path) -> None:
    operations = FakeOperations({"can_start": False, "blockers": ["private_stream_ready"]}, {})
    services = SimpleNamespace(operations=operations, campaign=FakeCampaign([]), reports=FakeReports())
    result = run(_args(tmp_path), services)
    assert result["status"] == "blocked"
    assert result["real_fill_evidence_confirmed"] is False
    assert operations.start_calls == 0
    assert (tmp_path / "launch-plan.json").exists()


def test_runner_resumes_only_same_campaign_without_bypassing_other_blockers(tmp_path) -> None:
    running = {
        "campaign_id": "campaign_resume",
        "experiment_id": "experiment_1",
        "scope": "BTCUSDT",
        "status": "running",
        "metrics": {"matched_fill_count": 19},
        "failed_gates": ["minimum_20_matched_fills_pending"],
    }
    operations = FakeOperations({"can_start": False, "blockers": ["no_active_campaign"]}, {})
    services = SimpleNamespace(operations=operations, campaign=FakeCampaign([running, _completed("campaign_resume")]), reports=FakeReports())
    result = run(_args(tmp_path, resume_campaign_id="campaign_resume"), services, sleep=lambda _: None, monotonic=lambda: 0.0)
    assert result["real_fill_evidence_confirmed"] is True
    assert operations.start_calls == 0
    blocked_operations = FakeOperations({"can_start": False, "blockers": ["no_active_campaign", "private_stream_ready"]}, {})
    blocked = SimpleNamespace(operations=blocked_operations, campaign=FakeCampaign([running]), reports=FakeReports())
    result = run(_args(tmp_path / "blocked", resume_campaign_id="campaign_resume"), blocked)
    assert result["reason"] == "resume_plan_blocked"
    assert result["real_fill_evidence_confirmed"] is False
