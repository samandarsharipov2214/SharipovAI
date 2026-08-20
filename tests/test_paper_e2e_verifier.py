from __future__ import annotations

from pathlib import Path

from ai_architecture_registry import CANONICAL_AI_ORGANS
from autonomous_trading.trade_identity import scope_for_path
from storage import ProjectDatabase
from tools.paper_e2e_verifier import (
    collect_snapshot,
    verify_restart_recovery,
    write_restart_baseline,
)


def _database(tmp_path: Path) -> ProjectDatabase:
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'shared.db'}")
    database.initialize()
    return database


def _safe_env(monkeypatch) -> None:
    monkeypatch.setenv("EXECUTION_KILL_SWITCH", "1")
    monkeypatch.setenv("EXCHANGE_LIVE_TRADING_ENABLED", "0")
    monkeypatch.setenv("TESTNET_EXECUTION_ENABLED", "0")
    monkeypatch.setenv("AUTONOMOUS_TESTNET_ENABLED", "0")
    monkeypatch.setenv("AUTONOMOUS_TESTNET_BRIDGE_ENABLED", "0")
    monkeypatch.setenv("AUTONOMOUS_PAPER_STATE_FILE", "data/autonomous_paper.json")


def _healthy_organs(database: ProjectDatabase) -> None:
    for organ in CANONICAL_AI_ORGANS:
        database.put_json(
            "ai_organ_runtime",
            organ.id,
            {
                "organ_id": organ.id,
                "status": "healthy",
                "evidence": [f"verified:{organ.id}"],
                "blockers": [],
                "checked_at_ms": 1_800_000_000_000,
            },
        )


def test_complete_verified_round_trip_and_restart_recovery(tmp_path: Path, monkeypatch) -> None:
    _safe_env(monkeypatch)
    database = _database(tmp_path)
    _healthy_organs(database)
    scope = scope_for_path(Path("data/autonomous_paper.json"))
    database.put_json(
        "autonomous_paper_state",
        scope,
        {
            "cash": 10_005.0,
            "equity": 10_005.0,
            "realized_pnl": 5.0,
            "total_fees": 2.0,
            "positions": {},
        },
    )
    database.put_json(
        "paper_v2_decisions",
        "decision-1",
        {
            "decision_id": "decision-1",
            "decided_at_ms": 900,
            "paper_decision_owner": "general_controller_v2",
            "authorized": True,
            "controller": {"final_intent": "BUY"},
            "execution_authority": False,
        },
    )
    database.put_json(
        "paper_authorization_consumption",
        "decision-1",
        {
            "decision_id": "decision-1",
            "decision": "ALLOW",
            "consumed_at_ms": 950,
            "paper_decision_owner": "general_controller_v2",
            "execution_authority": False,
        },
    )
    database.put_json(
        f"paper_trades:{scope}",
        "buy-1",
        {
            "trade_id": "buy-1",
            "created_at_ms": 1000,
            "symbol": "BTCUSDT",
            "side": "BUY",
            "decision_id": "decision-1",
            "candidate_id": "decision-1",
            "verified_market_data": True,
            "canonical_entry_authorized": True,
            "decision_quality_confidence": 82.0,
            "decision_quality_agreement": 0.81,
            "general_controller_decision": "ALLOW",
        },
    )
    database.put_json(
        f"paper_trades:{scope}",
        "sell-1",
        {
            "trade_id": "sell-1",
            "created_at_ms": 2000,
            "symbol": "BTCUSDT",
            "side": "SELL",
            "decision_id": "decision-1",
            "verified_market_data": True,
            "net_pnl": 5.0,
        },
    )
    database.put_json(
        "paper_decision_settlements",
        "decision-1",
        {
            "decision_id": "decision-1",
            "selected_action": "BUY",
            "realized_outcome": "PROFIT",
            "reputation_recorded": False,
            "legacy_direction_labeling_disabled": True,
            "learning_mode": "v2_role_aware_pending_replay",
            "verified_market_data": True,
            "net_pnl": 5.0,
        },
    )
    database.put_json(
        "council_decision_trace",
        "BTCUSDT",
        {
            "symbol": "BTCUSDT",
            "status": "SELL",
            "phase": "protective_exit",
            "reason": "protective_take_profit",
            "market_verified": True,
            "updated_at_ms": 2000,
        },
    )

    snapshot = collect_snapshot(database)

    assert snapshot["financial_locks_safe"] is True
    assert snapshot["ai_organs"]["healthy"] == 9
    assert snapshot["e2e_chain_complete"] is True
    assert snapshot["release_evidence_complete"] is True
    assert snapshot["round_trip"]["decision_id"] == "decision-1"
    assert snapshot["round_trip"]["paper_decision_owner"] == "general_controller_v2"
    assert all(snapshot["round_trip"]["chain"].values())

    baseline = write_restart_baseline(database)
    assert baseline["buy_trade_id"] == "buy-1"
    assert baseline["paper_decision_owner"] == "general_controller_v2"
    recovered = verify_restart_recovery(database)
    assert recovered["recovery_verified"] is True
    assert all(recovered["checks"].values())


def test_waiting_state_reports_exact_trace_and_does_not_fake_success(tmp_path: Path, monkeypatch) -> None:
    _safe_env(monkeypatch)
    database = _database(tmp_path)
    scope = scope_for_path(Path("data/autonomous_paper.json"))
    database.put_json(
        "autonomous_paper_state",
        scope,
        {
            "cash": 10_000.0,
            "equity": 10_000.0,
            "realized_pnl": 0.0,
            "total_fees": 0.0,
            "positions": {},
        },
    )
    database.put_json(
        "council_decision_trace",
        "ETHUSDT",
        {
            "symbol": "ETHUSDT",
            "status": "WAIT",
            "phase": "preflight",
            "reason": "cross-exchange consensus requires 3 sources; got 2",
            "market_verified": True,
            "consensus_source_count": 2,
            "required_consensus_source_count": 3,
            "updated_at_ms": 3000,
        },
    )

    snapshot = collect_snapshot(database)

    assert snapshot["e2e_chain_complete"] is False
    assert snapshot["release_evidence_complete"] is False
    assert snapshot["ai_organs"]["healthy"] == 0
    assert snapshot["decision_traces"][0]["symbol"] == "ETHUSDT"
    assert "requires 3 sources; got 2" in snapshot["decision_traces"][0]["reason"]
