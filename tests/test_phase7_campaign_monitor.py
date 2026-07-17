from __future__ import annotations

import json

from campaigns.phase7_monitor import Phase7CampaignMonitor
from storage import ProjectDatabase


class _Executions:
    def snapshot(self):
        return {
            "managed_orders": [
                {
                    "order_link_id": "sai_campaign",
                    "symbol": "BTCUSDT",
                    "side": "Buy",
                    "filled_quantity": 0.0002,
                    "average_fill_price": 60_000.0,
                    "actual_fee": 0.012,
                    "fee_currency": "USDT",
                    "first_exec_time_ms": 1_800_000_000_100,
                    "last_exec_time_ms": 1_800_000_000_200,
                    "exec_ids": ["exec_actual_1"],
                },
                {
                    "order_link_id": "sai_foreign",
                    "symbol": "ETHUSDT",
                    "actual_fee": 99.0,
                    "exec_ids": ["exec_foreign"],
                },
            ]
        }


class _Campaign:
    def __init__(self):
        self.executions = _Executions()
        self.row = {
            "campaign_id": "campaign_phase7",
            "experiment_id": "experiment_phase7",
            "scope": "BTCUSDT",
            "status": "completed",
            "cycle_count": 7,
            "policy": {"minimum_matched_fills": 20},
            "metrics": {
                "matched_fill_count": 20,
                "unmatched_paper_count": 0,
                "unmatched_testnet_count": 0,
                "orphan_execution_count": 0,
                "duplicate_order_count": 0,
                "unresolved_order_count": 0,
            },
            "failed_gates": [],
            "last_evidence": {"private_stream": {"ready": True, "status": "ready"}},
            "final_report_id": "report_phase7",
        }

    def get(self, campaign_id: str):
        return dict(self.row) if campaign_id == self.row["campaign_id"] else None

    def _campaign_records(self, campaign_id: str):
        assert campaign_id == self.row["campaign_id"]
        return [{"order_link_id": "sai_campaign", "campaign_id": campaign_id}]


class _Operations:
    def __init__(self, campaign):
        self.campaign = campaign

    def snapshot(self):
        return {
            "status": "ok",
            "active_campaign_count": 0,
            "active_campaign": {},
            "latest_campaign": dict(self.campaign.row),
            "plan": {"status": "ready", "gates": {}, "blockers": []},
        }


class _Reports:
    def get(self, report_id: str):
        if report_id == "report_phase7":
            return {
                "report_id": report_id,
                "status": "eligible_for_manual_decision",
                "manual_decision_required": True,
            }
        return None


def _monitor(tmp_path):
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'phase7.db'}")
    campaign = _Campaign()
    return Phase7CampaignMonitor(
        database,
        campaign=campaign,
        operations=_Operations(campaign),
        reports=_Reports(),
        report_directory=tmp_path / "reports",
    )


def test_monitor_projects_only_campaign_bound_private_fills(tmp_path) -> None:
    monitor = _monitor(tmp_path)
    snapshot = monitor.refresh(now_ms=1_800_000_001_000)

    assert snapshot["status"] == "completed"
    assert snapshot["progress"] == {
        "matched_fills": 20,
        "target_fills": 20,
        "remaining_fills": 0,
        "percent": 100.0,
    }
    assert snapshot["actual_fill_count"] == 1
    assert snapshot["actual_fee_total"] == 0.012
    assert snapshot["actual_fills"][0]["exec_ids"] == ["exec_actual_1"]
    assert snapshot["actual_fills"][0]["private_evidence"] is True
    assert snapshot["mainnet_enabled"] is False
    assert snapshot["runtime_flags_changed"] is False


def test_monitor_exports_atomic_final_report_with_actual_fills(tmp_path) -> None:
    monitor = _monitor(tmp_path)
    snapshot = monitor.refresh(now_ms=1_800_000_001_000)
    path = tmp_path / "reports" / "campaign_phase7.json"

    assert snapshot["final_report_ready"] is True
    assert snapshot["final_report_path"] == str(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["campaign"]["campaign_id"] == "campaign_phase7"
    assert payload["actual_private_fills"][0]["order_link_id"] == "sai_campaign"
    assert payload["final_promotion_report"]["report_id"] == "report_phase7"
    assert payload["mainnet_enabled"] is False


def test_snapshot_reports_stale_heartbeat_without_mutating_authority(tmp_path) -> None:
    monitor = _monitor(tmp_path)
    monitor.refresh(now_ms=1_800_000_000_000)
    stale = monitor.snapshot(now_ms=1_800_000_100_000)

    assert stale["heartbeat_stale"] is False  # completed campaigns are terminal
    assert "monitor_heartbeat_stale" not in stale["alerts"]
    assert stale["runtime_flags_changed"] is False
    assert stale["mainnet_enabled"] is False
