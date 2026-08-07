"""Read-only Paper E2E and nine-organ verifier for production evidence.

The verifier never creates orders, ticks the runtime, changes thresholds, or
changes execution flags. It reads the canonical ProjectDatabase and can persist
only a restart-verification baseline in its own namespace.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any, Mapping

from ai_architecture_registry import CANONICAL_AI_ORGANS
from autonomous_trading.trade_identity import scope_for_path
from storage import ProjectDatabase, list_json_items

BASELINE_NAMESPACE = "paper_e2e_verification"
BASELINE_KEY = "restart_baseline"


def _truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _paper_scope() -> str:
    state_file = Path(os.getenv("AUTONOMOUS_PAPER_STATE_FILE", "data/autonomous_paper.json"))
    return scope_for_path(state_file)


def _values(database: ProjectDatabase, namespace: str) -> list[dict[str, Any]]:
    rows = list_json_items(database, namespace, limit=10_000, newest_first=False)
    return [dict(row["value"]) for row in rows if isinstance(row.get("value"), Mapping)]


def _financial_locks() -> dict[str, bool]:
    return {
        "execution_kill_switch": _truthy("EXECUTION_KILL_SWITCH"),
        "live_execution_disabled": not _truthy("EXCHANGE_LIVE_TRADING_ENABLED"),
        "testnet_execution_disabled": not _truthy("TESTNET_EXECUTION_ENABLED"),
        "autonomous_testnet_disabled": not _truthy("AUTONOMOUS_TESTNET_ENABLED"),
        "testnet_bridge_disabled": not _truthy("AUTONOMOUS_TESTNET_BRIDGE_ENABLED"),
    }


def _organ_snapshot(database: ProjectDatabase) -> dict[str, Any]:
    organs: list[dict[str, Any]] = []
    healthy = 0
    for organ in CANONICAL_AI_ORGANS:
        row = database.get_json("ai_organ_runtime", organ.id)
        value = dict(row.get("value") or {}) if isinstance(row, Mapping) else {}
        status = str(value.get("status") or "missing")
        if status == "healthy":
            healthy += 1
        organs.append(
            {
                "organ_id": organ.id,
                "status": status,
                "evidence": list(value.get("evidence") or []),
                "blockers": list(value.get("blockers") or []),
                "checked_at_ms": int(value.get("checked_at_ms") or 0),
            }
        )
    return {
        "healthy": healthy,
        "total": len(CANONICAL_AI_ORGANS),
        "all_healthy": healthy == len(CANONICAL_AI_ORGANS),
        "organs": organs,
    }


def _decision_traces(database: ProjectDatabase) -> list[dict[str, Any]]:
    traces = _values(database, "council_decision_trace")
    traces.sort(key=lambda item: int(item.get("updated_at_ms") or 0), reverse=True)
    return [
        {
            "symbol": str(item.get("symbol") or ""),
            "status": str(item.get("status") or ""),
            "phase": str(item.get("phase") or ""),
            "reason": str(item.get("reason") or "")[:800],
            "market_verified": item.get("market_verified"),
            "consensus_source_count": item.get("consensus_source_count"),
            "required_consensus_source_count": item.get("required_consensus_source_count"),
            "quote_age_ms": item.get("quote_age_ms"),
            "vote_counts": item.get("vote_counts") or {},
            "risk_blocks": item.get("risk_blocks") or [],
            "decision_quality_confidence": item.get("decision_quality_confidence"),
            "decision_quality_agreement": item.get("decision_quality_agreement"),
            "updated_at_ms": int(item.get("updated_at_ms") or 0),
        }
        for item in traces
    ]


def _completed_round_trip(database: ProjectDatabase, scope: str) -> dict[str, Any] | None:
    trades = _values(database, f"paper_trades:{scope}")
    buys = [
        item
        for item in trades
        if str(item.get("side") or "").upper() == "BUY"
        and str(item.get("decision_id") or "").strip()
        and item.get("canonical_entry_authorized") is True
        and item.get("verified_market_data") is True
    ]
    for buy in reversed(buys):
        decision_id = str(buy.get("decision_id") or "").strip()
        buy_ms = int(buy.get("created_at_ms") or 0)
        sells = [
            item
            for item in trades
            if str(item.get("side") or "").upper() == "SELL"
            and str(item.get("decision_id") or "").strip() == decision_id
            and int(item.get("created_at_ms") or 0) >= buy_ms
            and item.get("verified_market_data") is True
        ]
        if not sells:
            continue
        sell = sells[-1]
        settlement_row = database.get_json("paper_decision_settlements", decision_id)
        settlement = (
            dict(settlement_row.get("value") or {})
            if isinstance(settlement_row, Mapping)
            else {}
        )
        if not settlement:
            continue
        return {
            "decision_id": decision_id,
            "candidate_id": str(buy.get("candidate_id") or ""),
            "symbol": str(buy.get("symbol") or ""),
            "buy_trade_id": str(buy.get("trade_id") or ""),
            "sell_trade_id": str(sell.get("trade_id") or ""),
            "buy_created_at_ms": buy_ms,
            "sell_created_at_ms": int(sell.get("created_at_ms") or 0),
            "net_pnl": sell.get("net_pnl"),
            "decision_quality_confidence": buy.get("decision_quality_confidence"),
            "decision_quality_agreement": buy.get("decision_quality_agreement"),
            "general_controller_decision": buy.get("general_controller_decision"),
            "settlement": settlement,
            "chain": {
                "market_verified": buy.get("verified_market_data") is True,
                "council_authorized": buy.get("canonical_entry_authorized") is True,
                "decision_quality_recorded": bool(
                    buy.get("decision_quality_confidence") is not None
                    and buy.get("decision_quality_agreement") is not None
                ),
                "paper_buy": True,
                "paper_sell": True,
                "pnl_recorded": sell.get("net_pnl") is not None,
                "evidence_persisted": bool(settlement),
                "learning_settled": bool(
                    settlement.get("reputation_recorded") is True
                    or settlement.get("lessons")
                ),
            },
        }
    return None


def collect_snapshot(database: ProjectDatabase | None = None) -> dict[str, Any]:
    database = database or ProjectDatabase()
    database.initialize()
    scope = _paper_scope()
    state_row = database.get_json("autonomous_paper_state", scope)
    state = dict(state_row.get("value") or {}) if isinstance(state_row, Mapping) else {}
    round_trip = _completed_round_trip(database, scope)
    organs = _organ_snapshot(database)
    locks = _financial_locks()
    chain = dict((round_trip or {}).get("chain") or {})
    chain_complete = bool(chain) and all(chain.values())
    return {
        "generated_at_ms": int(time.time() * 1000),
        "database": database.health(),
        "paper_scope": scope,
        "financial_locks": locks,
        "financial_locks_safe": all(locks.values()),
        "paper_state_present": bool(state),
        "paper_state": {
            "cash": state.get("cash"),
            "equity": state.get("equity"),
            "realized_pnl": state.get("realized_pnl"),
            "total_fees": state.get("total_fees"),
            "open_symbols": sorted((state.get("positions") or {}).keys())
            if isinstance(state.get("positions"), Mapping)
            else [],
        },
        "round_trip": round_trip,
        "e2e_chain_complete": chain_complete,
        "ai_organs": organs,
        "decision_traces": _decision_traces(database),
        "release_evidence_complete": bool(chain_complete and organs["all_healthy"] and all(locks.values())),
    }


def write_restart_baseline(database: ProjectDatabase | None = None) -> dict[str, Any]:
    database = database or ProjectDatabase()
    snapshot = collect_snapshot(database)
    round_trip = snapshot.get("round_trip")
    if not snapshot.get("e2e_chain_complete") or not isinstance(round_trip, Mapping):
        raise RuntimeError("a complete verified Paper BUY->SELL settlement is required before restart")
    baseline = {
        "created_at_ms": int(time.time() * 1000),
        "decision_id": str(round_trip.get("decision_id") or ""),
        "buy_trade_id": str(round_trip.get("buy_trade_id") or ""),
        "sell_trade_id": str(round_trip.get("sell_trade_id") or ""),
        "symbol": str(round_trip.get("symbol") or ""),
        "net_pnl": round_trip.get("net_pnl"),
    }
    database.put_json(BASELINE_NAMESPACE, BASELINE_KEY, baseline)
    return baseline


def verify_restart_recovery(database: ProjectDatabase | None = None) -> dict[str, Any]:
    database = database or ProjectDatabase()
    database.initialize()
    baseline_row = database.get_json(BASELINE_NAMESPACE, BASELINE_KEY)
    baseline = (
        dict(baseline_row.get("value") or {})
        if isinstance(baseline_row, Mapping)
        else {}
    )
    if not baseline:
        raise RuntimeError("restart baseline is missing")
    scope = _paper_scope()
    trades = _values(database, f"paper_trades:{scope}")
    trade_ids = {str(item.get("trade_id") or "") for item in trades}
    decision_id = str(baseline.get("decision_id") or "")
    settlement = database.get_json("paper_decision_settlements", decision_id)
    state = database.get_json("autonomous_paper_state", scope)
    checks = {
        "paper_state_reloaded": bool(state and isinstance(state.get("value"), Mapping)),
        "buy_history_recovered": str(baseline.get("buy_trade_id") or "") in trade_ids,
        "sell_history_recovered": str(baseline.get("sell_trade_id") or "") in trade_ids,
        "settlement_recovered": bool(settlement and isinstance(settlement.get("value"), Mapping)),
    }
    return {
        "baseline": baseline,
        "checks": checks,
        "recovery_verified": all(checks.values()),
        "ai_organs": _organ_snapshot(database),
        "financial_locks": _financial_locks(),
    }


def _print_human(snapshot: Mapping[str, Any]) -> None:
    print(f"PAPER_E2E_COMPLETE={str(bool(snapshot.get('e2e_chain_complete'))).lower()}")
    organs = snapshot.get("ai_organs") or {}
    print(f"AI_ORGANS={organs.get('healthy', 0)}/{organs.get('total', 9)}")
    print(f"FINANCIAL_LOCKS_SAFE={str(bool(snapshot.get('financial_locks_safe'))).lower()}")
    round_trip = snapshot.get("round_trip")
    if isinstance(round_trip, Mapping):
        print(
            "ROUND_TRIP="
            f"{round_trip.get('symbol')} decision={round_trip.get('decision_id')} "
            f"buy={round_trip.get('buy_trade_id')} sell={round_trip.get('sell_trade_id')} "
            f"net_pnl={round_trip.get('net_pnl')}"
        )
    else:
        print("ROUND_TRIP=waiting for a natural canonical Paper BUY -> SELL")
    for trace in list(snapshot.get("decision_traces") or [])[:10]:
        print(
            "TRACE "
            f"{trace.get('symbol')} {trace.get('status')} {trace.get('phase')}: "
            f"{trace.get('reason')}"
        )
    for organ in (organs.get("organs") or []):
        if organ.get("status") != "healthy":
            print(
                f"ORGAN {organ.get('organ_id')}={organ.get('status')} "
                f"blockers={'; '.join(organ.get('blockers') or [])}"
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--watch-seconds", type=int, default=0)
    parser.add_argument("--interval-seconds", type=int, default=10)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--prepare-restart", action="store_true")
    parser.add_argument("--verify-restart", action="store_true")
    args = parser.parse_args(argv)

    if args.prepare_restart and args.verify_restart:
        parser.error("choose only one restart mode")

    database = ProjectDatabase()
    if args.prepare_restart:
        baseline = write_restart_baseline(database)
        print(json.dumps({"restart_baseline": baseline}, ensure_ascii=False, indent=2))
        return 0
    if args.verify_restart:
        result = verify_restart_recovery(database)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["recovery_verified"] else 2

    deadline = time.monotonic() + max(args.watch_seconds, 0)
    while True:
        snapshot = collect_snapshot(database)
        if args.json:
            print(json.dumps(snapshot, ensure_ascii=False, indent=2))
        else:
            _print_human(snapshot)
        if snapshot["release_evidence_complete"]:
            return 0
        if args.watch_seconds <= 0 or time.monotonic() >= deadline:
            return 2
        time.sleep(max(args.interval_seconds, 5))


if __name__ == "__main__":
    raise SystemExit(main())
