from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from autonomous_trading.forecast_contract import digest
from learning_engine.forecast_readiness import DAY, INTERVAL_MS, NAMESPACE, advance, new_state, readiness
from scripts.paper_forecast_readiness import check, register
from storage import ProjectDatabase


@pytest.fixture
def prepared(tmp_path):
    db = ProjectDatabase(f"sqlite:///{tmp_path / 'canonical.db'}")
    db.initialize()
    template = json.loads(Path("docs/paper-next-model-specification.json").read_text())
    plan = register(db, now_ms=100 * DAY, template=template)
    db.put_json("alpha_holdout_consumption", digest(["canonical_paper_opportunities", plan["scope"]]),
                {"schema_version": 2, "claims": {}})
    return db, plan


def event(plan, rid, at, **changes):
    row = {"scope": plan["scope"], "symbol": "BTCUSDT", "decision_time_ms": at,
           "recorded_at_ms": at + 1, "market_verified": True, "capture_digest": "a" * 64,
           "quote": {"bid_price": 99, "ask_price": 101, "received_at_unix_ms": at,
                     "feature_received_at_ms": at, "change_24h_percent": 1, "volume_24h": 1e6},
           "cost_model": {"fee_rate": .001, "slippage_bps": 1, "market_impact_bps": 1,
                          "max_participation_rate": .01}, **changes}
    return {"rowid": rid, "event_id": str(rid), "stored_at_ms": at + 1, "value": row}


def test_counts_mature_metadata_without_return_or_model_fields(prepared):
    _, plan = prepared
    at = plan["source_start_ms"]
    events = [event(plan, 1, at), event(plan, 2, at + 300_000)]
    state = advance(new_state(plan, cursor=0), plan, events, now_ms=at + 400_000)
    assert state["partitions"]["train"]["valid"] == 1
    encoded = json.dumps(state)
    assert all(word not in encoded for word in ("bid_price", "ask_price", "target_return", "net_pnl", "prediction"))
    assert state["execution_authority"] is False
    result = readiness(state, plan, now_ms=at + 400_000, caught_up=True, claims={})
    assert result["ready"] is False and result["holdout_opened"] is False


@pytest.mark.parametrize("defect", ["missing_feature", "future_feature", "late_capture", "wrong_physical_time"])
def test_invalid_lineage_is_never_readiness_support(prepared, defect):
    _, plan = prepared
    at = plan["source_start_ms"]
    entry, future = event(plan, 1, at), event(plan, 2, at + 300_000)
    if defect == "missing_feature":
        del entry["value"]["quote"]["feature_received_at_ms"]
    elif defect == "future_feature":
        entry["value"]["quote"]["feature_received_at_ms"] += 1
    elif defect == "late_capture":
        entry["value"]["recorded_at_ms"] += 300_000
        entry["stored_at_ms"] += 300_000
    else:
        entry["stored_at_ms"] += 1
    state = advance(new_state(plan, cursor=0), plan, [entry, future], now_ms=at + 400_000)
    assert state["partitions"]["train"]["anchors"] == 1
    assert state["partitions"]["train"]["matured"] == 1
    assert state["partitions"]["train"]["valid"] == 0


def test_missing_label_and_cross_boundary_label_remain_in_denominator(prepared):
    _, plan = prepared
    at = plan["calibration_start_ms"] - 200_000
    state = advance(new_state(plan, cursor=0), plan,
                    [event(plan, 1, at), event(plan, 2, at + 300_000)], now_ms=at + 400_000)
    assert state["rejections"]["purged_boundary_label"] == 1
    at = plan["source_start_ms"]
    state = advance(new_state(plan, cursor=0), plan,
                    [event(plan, 1, at), event(plan, 2, at + 320_000)], now_ms=at + 400_000)
    assert state["rejections"]["missing_future_quote"] == 1


def supported_state(plan):
    state = new_state(plan, cursor=0)
    state.update(rows=5000, verified_quotes=5000, feature_timestamp_present=5000,
                 first_source_ms=plan["source_start_ms"], last_source_ms=plan["holdout_end_ms"])
    for part, stats in state["partitions"].items():
        stats.update(anchors=1000, matured=1000, valid=900,
                     first_valid_ms=plan["holdout_start_ms"], last_valid_ms=plan["holdout_end_ms"]-400_000,
                     symbols={s:180 for s in plan["symbols"]},
                     regimes={r:300 for r in ("up_24h", "down_24h", "range_24h")})
    return state


def test_frozen_plan_cooldown_and_exactly_one_request(prepared):
    db, plan = prepared
    now = plan["holdout_end_ms"] + 1
    db.put_json(NAMESPACE, "state", supported_state(plan))
    first = check(db, now_ms=now)
    assert first["ready"] and first["request_continuation"]
    assert not first["holdout_opened"] and not first["model_promoted"]
    assert check(db, now_ms=now + 1)["reasons"] == ["six_hour_cooldown"]
    assert not check(db, now_ms=now + INTERVAL_MS)["request_continuation"]
    assert db.get_json("alpha_holdout_consumption", digest(["canonical_paper_opportunities", plan["scope"]]))["value"]["claims"] == {}
    with pytest.raises(ValueError, match="already_registered"):
        register(db, now_ms=now, template=plan)


def test_consumed_holdout_changed_plan_incomplete_source_and_groups_block(prepared):
    _, plan = prepared
    state = supported_state(plan)
    now = plan["holdout_end_ms"] + 1
    assert readiness(state, plan, now_ms=now, caught_up=True, claims={})["ready"]
    claims = {"old": {"final_oos_range": [plan["holdout_start_ms"], plan["holdout_end_ms"]]}}
    assert "holdout_already_consumed" in readiness(state, plan, now_ms=now, caught_up=True, claims=claims)["reasons"]
    assert not readiness(state, plan, now_ms=now, caught_up=False, claims={})["ready"]
    changed = copy.deepcopy(plan)
    changed["horizon_seconds"] = 1
    assert "frozen_plan_changed" in readiness(state, changed, now_ms=now, caught_up=True, claims={})["reasons"]
    state["partitions"]["test"]["symbols"]["BTCUSDT"] = 49
    assert not readiness(state, plan, now_ms=now, caught_up=True, claims={})["ready"]


def test_incremental_database_scan_reads_only_canonical_opportunities(prepared):
    db, plan = prepared
    at = plan["source_start_ms"]
    db.append_event("unrelated", "other", "ignore", {"private": "not-read"}, created_at_ms=at)
    for rid, offset in ((1, 0), (2, 300_000)):
        e = event(plan, rid, at + offset)
        db.append_event("paper_economic_opportunities:" + plan["scope"], "opportunity", str(rid), e["value"],
                        event_id=str(rid), created_at_ms=e["stored_at_ms"])
    report = check(db, now_ms=at + INTERVAL_MS)
    assert report["source_rows"] == 2
    assert report["testable_matured_labels"] == 1
    assert not report["request_continuation"]
    state = db.get_json(NAMESPACE, "state")["value"]
    with db.connect() as c:
        c.execute("UPDATE project_events SET event_id='changed' WHERE rowid=?", (state["anchor_rowid"],))
    with pytest.raises(ValueError, match="cursor_rewritten"):
        check(db, now_ms=at + 2 * INTERVAL_MS)
