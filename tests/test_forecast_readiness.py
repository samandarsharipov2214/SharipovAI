from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from autonomous_trading.forecast_contract import digest
from learning_engine.forecast_readiness import DAY, INTERVAL_MS, NAMESPACE, advance, expected_anchors, new_state, readiness
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


def test_real_capture_integral_float_timestamps_are_accepted(prepared):
    _, plan = prepared
    at = plan["source_start_ms"]
    events = [event(plan, 1, at), event(plan, 2, at + 300_000)]
    for e in events:
        for key in ("received_at_unix_ms", "feature_received_at_ms"):
            e["value"]["quote"][key] = float(e["value"]["quote"][key])
    state = advance(new_state(plan, cursor=0), plan, events, now_ms=at + 400_000)
    assert state["partitions"]["train"]["valid"] == 1
    assert state["feature_timestamp_present"] == state["verified_quotes"] == 2


@pytest.mark.parametrize("bad", [True, 1.5, float("inf"), float("nan"), "1000"])
def test_noncanonical_timestamp_types_never_count(prepared, bad):
    _, plan = prepared
    at = plan["source_start_ms"]
    entry, future = event(plan, 1, at), event(plan, 2, at + 300_000)
    entry["value"]["quote"]["feature_received_at_ms"] = bad
    state = advance(new_state(plan, cursor=0), plan, [entry, future], now_ms=at + 400_000)
    assert state["partitions"]["train"]["valid"] == 0


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
        count = expected_anchors(plan, part)
        stats.update(anchors=count, matured=count, valid=count,
                     first_valid_ms=plan["holdout_start_ms"], last_valid_ms=plan["holdout_end_ms"]-400_000,
                     symbols={s:count // len(plan["symbols"]) for s in plan["symbols"]},
                     regimes={r:count // 3 for r in ("up_24h", "down_24h", "range_24h")})
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


def test_live_watermark_precedes_validation_clock_and_defers_later_writers(prepared, monkeypatch):
    from contextlib import contextmanager
    import scripts.paper_forecast_readiness as runner
    db, plan = prepared
    at = plan["source_start_ms"]
    clock = [at]
    original = db.connect
    inserted = [False]

    class Connection:
        def __init__(self, raw):
            self.raw = raw

        def __getattr__(self, key):
            return getattr(self.raw, key)

        def execute(self, sql, params=()):
            if sql.startswith("SELECT coalesce(max(rowid)") and not inserted[0]:
                inserted[0] = True
                # Writer commits after invocation but before the watermark.
                clock[0] += 100
                e = event(plan, 1, clock[0] - 1)
                db.append_event("paper_economic_opportunities:" + plan["scope"], "opportunity", "one",
                                e["value"], created_at_ms=e["stored_at_ms"])
            return self.raw.execute(sql, params)

    @contextmanager
    def connect():
        with original() as raw:
            yield Connection(raw)

    def validation_clock():
        assert inserted[0], "clock must follow the source watermark"
        e = event(plan, 2, clock[0] + 1)
        db.append_event("paper_economic_opportunities:" + plan["scope"], "opportunity", "two",
                        e["value"], created_at_ms=e["stored_at_ms"])
        return clock[0] / 1000

    monkeypatch.setattr(db, "connect", connect)
    monkeypatch.setattr(runner.time, "time", validation_clock)
    # ProjectDatabase's own clock must remain independent of this simulated read.
    monkeypatch.setattr("storage.project_database._now_ms", lambda: clock[0])
    result = check(db)
    state = db.get_json(NAMESPACE, "state")["value"]
    assert result["source_rows"] == 1 and not state["fatal_errors"]
    result = check(db, now_ms=clock[0] + INTERVAL_MS)
    assert result["source_rows"] == 2
    assert not db.get_json(NAMESPACE, "state")["value"]["fatal_errors"]


def test_unpersisted_source_gaps_cannot_report_full_coverage(prepared):
    _, plan = prepared
    state = supported_state(plan)
    for part, counts in state["partitions"].items():
        # Every surviving observation was valid, but 30% were never captured.
        count = int(expected_anchors(plan, part) * .7)
        counts.update(anchors=count, matured=count, valid=count)
    result = readiness(state, plan, now_ms=plan["holdout_end_ms"] + 1, caught_up=True, claims={})
    assert not result["ready"]
    assert all(part + "_coverage_below_80_percent" in result["reasons"] for part in state["partitions"])
    assert all(c["valid_fraction"] <= .7 for c in result["coverage"].values())


def test_changed_algorithm_never_reuses_incremental_counters(prepared, monkeypatch):
    import scripts.paper_forecast_readiness as runner
    db, plan = prepared
    state = supported_state(plan)
    db.put_json(NAMESPACE, "state", state)
    monkeypatch.setattr(runner, "algorithm_identity", lambda: {"version": "different"})
    with pytest.raises(ValueError, match="readiness_algorithm_changed"):
        check(db, now_ms=plan["holdout_end_ms"] + 1)
    assert db.get_json(NAMESPACE, "state")["value"] == state


def test_deadline_interruption_preserves_completed_batches(prepared, monkeypatch):
    import sqlite3
    from contextlib import contextmanager
    import scripts.paper_forecast_readiness as runner
    db, plan = prepared
    at = plan["source_start_ms"]
    with db.connect() as c:
        c.execute("INSERT INTO project_events (event_id,namespace,entity_type,entity_id,payload_json,created_at_ms) "
                  "VALUES ('gap','other','other','other','{}',?)", (at,))
        c.execute("UPDATE project_events SET rowid=11000 WHERE event_id='gap'")
    original = db.connect
    clock, queries = [0], []

    class InterruptedConnection:
        def __init__(self, connection):
            self.connection = connection
        def __getattr__(self, name):
            return getattr(self.connection, name)
        def execute(self, sql, parameters=()):
            if "NOT INDEXED" in sql:
                queries.append(parameters[:2])
                if len(queries) == 2:
                    clock[0] = 91
                    error = sqlite3.OperationalError("interrupted")
                    error.sqlite_errorcode = sqlite3.SQLITE_INTERRUPT
                    raise error
            return self.connection.execute(sql, parameters)

    @contextmanager
    def connect():
        with original() as c:
            yield InterruptedConnection(c)
    monkeypatch.setattr(db, "connect", connect)
    monkeypatch.setattr(runner.time, "monotonic", lambda: clock[0])
    first = check(db, now_ms=at + INTERVAL_MS)
    assert first["cursor"] == 5000 and not first["ready"]
    assert "source_cursor_not_caught_up" in first["reasons"]
    second = check(db, now_ms=at + 2 * INTERVAL_MS)
    assert second["cursor"] == 11000
    assert queries[2][0] == 5000  # Completed prefix was not rescanned.
