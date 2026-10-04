"""Bounded six-hour metadata check; no model or execution capability."""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

from autonomous_trading.forecast_contract import digest
from learning_engine.forecast_readiness import DAY, INTERVAL_MS, NAMESPACE, advance, new_state, readiness
from storage import ProjectDatabase

PLAN_ID = "paper-next-ridge-development-v2"
MAX_EVENTS = 100_000


def register(db: ProjectDatabase, *, now_ms: int, template: dict) -> dict:
    if db.backend != "sqlite":
        raise ValueError("readiness_cursor_requires_sqlite")
    if db.get_json(NAMESPACE, "plan"):
        raise ValueError("frozen_plan_already_registered")
    start = (now_ms // DAY + 1) * DAY
    plan = {**template, "plan_id": PLAN_ID, "registered_at_ms": now_ms,
            "source_start_ms": start, "calibration_start_ms": start + 21 * DAY,
            "holdout_start_ms": start + 28 * DAY, "holdout_end_ms": start + 36 * DAY,
            "holdout_status": "RESERVED_UNOPENED", "execution_authority": False}
    dataset_key = digest(["canonical_paper_opportunities", plan["scope"]])
    plan["holdout_identity"] = hashlib.sha256(
        f"{dataset_key}:{plan['holdout_start_ms']}:{plan['holdout_end_ms']}".encode()).hexdigest()
    with db.connect() as connection:
        cursor = connection.execute("SELECT coalesce(max(rowid),0) FROM project_events").fetchone()[0]
    # Creation is exclusive. A partial registration remains unavailable until
    # repaired explicitly; a retry cannot move the frozen dates or reopen OOS.
    db.put_json(NAMESPACE, "plan", plan, expected_version=0)
    db.put_json(NAMESPACE, "state", new_state(plan, cursor=cursor), expected_version=0)
    return plan


def check(db: ProjectDatabase, *, now_ms: int) -> dict:
    if db.backend != "sqlite":
        raise ValueError("readiness_cursor_requires_sqlite")
    plan_record, record = db.get_json(NAMESPACE, "plan"), db.get_json(NAMESPACE, "state")
    if not plan_record or not record:
        raise ValueError("frozen_plan_or_state_missing")
    plan, state = plan_record["value"], record["value"]
    if now_ms - state["last_checked_at_ms"] < INTERVAL_MS:
        return {"ready": False, "request_continuation": False, "reasons": ["six_hour_cooldown"]}
    if digest(plan) != state["plan_sha256"]:
        raise ValueError("frozen_plan_changed")
    # A short claim prevents concurrent invocations and crash retry storms.
    state["last_checked_at_ms"] = now_ms
    version = db.put_json(NAMESPACE, "state", state, expected_version=record["version"])
    deadline = time.monotonic() + 90
    processed = 0
    with db.connect() as c:
        high = c.execute("SELECT coalesce(max(rowid),0) FROM project_events").fetchone()[0]
        if high < state["cursor"]:
            raise ValueError("canonical_event_cursor_regressed")
        if state["anchor_rowid"] is not None:
            row = c.execute("SELECT event_id FROM project_events WHERE rowid=?", (state["anchor_rowid"],)).fetchone()
            if not row or row[0] != state["anchor_event_id"]:
                raise ValueError("canonical_event_cursor_rewritten")
    # Bound physical row scans, not only matching rows. Each batch closes its
    # reader before the next one, so the checker never pins a multi-hour WAL.
    while state["cursor"] < high and processed < MAX_EVENTS and time.monotonic() < deadline:
        end = min(high, state["cursor"] + 5000)
        with db.connect() as c:
            c.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
            rows = c.execute(
                "SELECT rowid,event_id,payload_json,created_at_ms FROM project_events NOT INDEXED "
                "WHERE rowid>? AND rowid<=? AND namespace=? AND entity_type='opportunity' ORDER BY rowid",
                (state["cursor"], end, "paper_economic_opportunities:" + plan["scope"])).fetchall()
        events = [{"rowid": row[0], "event_id": row[1], "value": json.loads(row[2]), "stored_at_ms": row[3]} for row in rows]
        processed += end - state["cursor"]
        state = advance(state, plan, events, now_ms=now_ms)
        state["cursor"] = end
    registry = db.get_json("alpha_holdout_consumption", digest(["canonical_paper_opportunities", plan["scope"]]))
    if not registry or registry["value"].get("schema_version") != 2:
        raise ValueError("canonical_holdout_registry_unavailable")
    result = readiness(state, plan, now_ms=now_ms, caught_up=state["cursor"] == high,
                       claims=registry["value"]["claims"])
    result.update(checked_at_ms=now_ms, scanned_rowids=processed, source_rows=state["rows"],
                  cursor=state["cursor"], source_tail=high, request_continuation=False)
    if result["ready"] and state["trigger_status"] == "not_requested":
        # At most one request, including across service restarts. A failed host
        # launch is an explicit operations error, never an automatic Astra retry.
        state["trigger_status"] = "requested_once"
        state["triggered_at_ms"] = now_ms
        result["request_continuation"] = True
    state["last_result"] = result
    db.put_json(NAMESPACE, "state", state, expected_version=version)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--register", type=Path, help="Freeze a new future specification exactly once")
    args = parser.parse_args()
    db = ProjectDatabase()
    now = int(time.time() * 1000)
    try:
        result = register(db, now_ms=now, template=json.loads(args.register.read_text())) if args.register else check(db, now_ms=now)
    except Exception as error:
        print(json.dumps({"ready": False, "request_continuation": False, "error_type": type(error).__name__,
                          "error": str(error) if isinstance(error, ValueError) else "readiness_check_failed"}))
        return 1
    print(json.dumps(result, allow_nan=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
