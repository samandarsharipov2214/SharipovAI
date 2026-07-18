from __future__ import annotations

import math

import pytest

from campaigns.phase9_results import CampaignResultsService, ScalingPolicy
from storage import ProjectDatabase


def _database(tmp_path):
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'phase9.db'}")
    database.initialize()
    return database


def _analysis(**overrides):
    value = {
        "campaign_id": "c1",
        "analysis_id": "a1",
        "generated_at_ms": 10,
        "fill_count": 2,
        "matched_fill_count": 2,
        "fee_ratio_bps": 5,
        "failed_gates": [],
        "pnl": {
            "gross_realized_pnl_usdt": 1.0,
            "fees_usdt": 0.2,
            "net_realized_pnl_usdt": 0.8,
            "closed_notional_usdt": 11.0,
            "return_on_closed_notional_bps": 727.272727,
            "open_inventory": {},
        },
        "divergence": {
            "actual_average_fill_price": 10.5,
            "paper_average_fill_price": 10.4979,
            "price_divergence_bps": 2.0,
            "actual_fee_total": 0.02,
            "expected_fee_total": 0.02,
            "fee_divergence_usdt": 0.0,
        },
    }
    value.update(overrides)
    return value


def _fills(exit_price=11):
    return [
        {
            "symbol": "BTCUSDT",
            "side": "Buy",
            "filled_quantity": 1,
            "average_fill_price": 10,
            "actual_fee": 0.01,
            "last_exec_time_ms": 1,
        },
        {
            "symbol": "BTCUSDT",
            "side": "Sell",
            "filled_quantity": 1,
            "average_fill_price": exit_price,
            "actual_fee": 0.01,
            "last_exec_time_ms": 2,
        },
    ]


def test_phase9_report_and_scaling_are_fail_closed(tmp_path):
    service = CampaignResultsService(
        _database(tmp_path),
        policy=ScalingPolicy(minimum_campaigns=1, minimum_fills=2),
    )
    report = service.build_report(_analysis(), _fills(), generated_at_ms=10)
    assert report["risk_metrics"]["closed_trade_count"] == 1
    assert report["risk_metrics"]["maximum_drawdown_bps"] == 0
    assert len(report["evidence_sha256"]) == 64
    plan = service.prepare_scaling(
        [report],
        actor="operator",
        reason="measured evidence",
    )
    assert plan["status"] == "eligible_for_manual_scaling_review"
    assert plan["automatic_scaling"] is False
    assert plan["runtime_flags_changed"] is False
    assert plan["mainnet_enabled"] is False


def test_exact_report_replay_is_idempotent(tmp_path):
    service = CampaignResultsService(_database(tmp_path))
    first = service.build_report(_analysis(), _fills(), generated_at_ms=10)
    replay = service.build_report(_analysis(), _fills(), generated_at_ms=999)
    assert replay == first
    assert len(service.list_reports()) == 1
    assert service.get_report("c1")["report_id"] == first["report_id"]


def test_changed_evidence_retains_history_and_updates_latest_index(tmp_path):
    service = CampaignResultsService(_database(tmp_path))
    first = service.build_report(_analysis(), _fills(), generated_at_ms=10)
    changed_analysis = _analysis(
        analysis_id="a2",
        generated_at_ms=11,
        pnl={
            **_analysis()["pnl"],
            "gross_realized_pnl_usdt": 2.0,
            "net_realized_pnl_usdt": 1.8,
        },
    )
    second = service.build_report(
        changed_analysis,
        _fills(exit_price=12),
        generated_at_ms=11,
    )
    assert first["report_id"] != second["report_id"]
    reports = service.list_reports()
    assert {item["report_id"] for item in reports} == {
        first["report_id"],
        second["report_id"],
    }
    assert service.get_report("c1")["report_id"] == second["report_id"]


def test_legacy_campaign_key_remains_readable(tmp_path):
    database = _database(tmp_path)
    database.put_json(
        "phase9_campaign_results",
        "legacy-campaign",
        {
            "schema_version": 1,
            "campaign_id": "legacy-campaign",
            "analysis_id": "legacy-analysis",
            "generated_at_ms": 1,
            "mainnet_enabled": False,
        },
        expected_version=0,
    )
    service = CampaignResultsService(database)
    assert service.get_report("legacy-campaign")["analysis_id"] == "legacy-analysis"


def test_corrupt_report_cannot_become_scaling_evidence(tmp_path):
    service = CampaignResultsService(
        _database(tmp_path),
        policy=ScalingPolicy(minimum_campaigns=1, minimum_fills=2),
    )
    report = service.build_report(_analysis(), _fills(), generated_at_ms=10)
    corrupt = dict(report)
    corrupt["pnl"] = {**report["pnl"], "net_realized_pnl_usdt": 999}
    plan = service.prepare_scaling(
        [corrupt],
        actor="operator",
        reason="must fail closed",
    )
    assert plan["status"] == "blocked"
    assert plan["gates"]["all_report_evidence_valid"] is False
    assert corrupt["report_id"] in plan["invalid_report_ids"]
    assert plan["campaign_ids"] == []


def test_duplicate_campaign_reports_do_not_inflate_scaling_counts(tmp_path):
    service = CampaignResultsService(
        _database(tmp_path),
        policy=ScalingPolicy(minimum_campaigns=2, minimum_fills=4),
    )
    first = service.build_report(_analysis(), _fills(), generated_at_ms=10)
    second = service.build_report(
        _analysis(analysis_id="a2", generated_at_ms=11),
        _fills(exit_price=12),
        generated_at_ms=11,
    )
    plan = service.prepare_scaling(
        [first, second],
        actor="operator",
        reason="same campaign cannot count twice",
    )
    assert plan["status"] == "blocked"
    assert plan["evidence"]["campaign_count"] == 1
    assert plan["gates"]["minimum_successful_campaigns"] is False


@pytest.mark.parametrize(
    "mutation",
    [
        {"fee_ratio_bps": math.nan},
        {"pnl": {"net_realized_pnl_usdt": math.inf}},
        {"divergence": {"price_divergence_bps": math.nan}},
    ],
)
def test_non_finite_analysis_evidence_is_rejected(tmp_path, mutation):
    service = CampaignResultsService(_database(tmp_path))
    with pytest.raises(ValueError, match="finite"):
        service.build_report(_analysis(**mutation), _fills(), generated_at_ms=10)


def test_non_finite_fill_is_rejected_instead_of_becoming_zero(tmp_path):
    service = CampaignResultsService(_database(tmp_path))
    fills = _fills()
    fills[0] = {**fills[0], "filled_quantity": math.nan}
    with pytest.raises(ValueError, match="finite"):
        service.build_report(_analysis(), fills, generated_at_ms=10)
