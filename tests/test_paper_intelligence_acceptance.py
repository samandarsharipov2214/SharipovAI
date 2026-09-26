"""Acceptance must expose lost history, bad cashflows and missing Learning."""
import copy

from scripts.paper_intelligence_acceptance import capture, compare
from storage import ProjectDatabase


def history(tmp_path):
    db = ProjectDatabase(f"sqlite:///{tmp_path / 'acceptance.db'}")
    db.initialize()
    for scope in ("active", "older"):
        decision = "decision-" + scope
        for side, price, fee, pnl, at in (("BUY", 100., .1, None, 1000), ("SELL", 110., .11, 9.79, 2000)):
            key = scope + side
            db.put_json("paper_trades:" + scope, key, {"trade_id": key, "decision_id": decision,
                "symbol": "BTCUSDT", "side": side, "price": price, "quantity": 1., "fee": fee,
                "net_pnl": pnl, "created_at_ms": at, "paper_strategy_version": "test-policy",
                "paper_build_sha": "test-build"})
        db.put_json("paper_decision_settlements", decision, {"decision_id": decision, "net_pnl": 9.79})
        db.put_json("self_learning_outcomes_v2", "paper:" + decision, {"net_pnl": 9.79})
    db.put_json("autonomous_paper_state", "active", {"cash": 109.79, "equity": 109.79,
        "positions": {}, "unrealized_pnl": 0., "trades": []})
    return db


def test_all_namespaces_are_reconciled_without_using_bounded_snapshot(tmp_path):
    report = capture(history(tmp_path), scope="active", since_ms=1500)
    assert report["history_count"] == 4 and report["settlement_count"] == 2
    assert report["active_scope"]["net_pnl"] == 9.79
    assert report["lifetime"]["net_pnl"] == 19.58
    assert report["post_deploy"]["executions"] == 1
    assert report["orphans"] == report["pnl_mismatches"] == report["accounting_issues"] == []
    assert report["learning_missing_or_mismatched"] == []
    after = copy.deepcopy(report)
    after["history_hashes"].pop(next(iter(after["history_hashes"])))
    assert compare(report, after)["history_preserved"] is False


def test_settlement_learning_and_balance_corruption_are_explicit(tmp_path):
    db = history(tmp_path)
    db.put_json("paper_decision_settlements", "decision-active", {"net_pnl": 100.})
    db.put_json("self_learning_outcomes_v2", "paper:decision-active", {"net_pnl": 0.})
    db.put_json("autonomous_paper_state", "active", {"cash": 100., "equity": 200., "positions": {},
        "pending_authorized_executions": {"pending": {}}})
    report = capture(db, scope="active")
    assert len(report["pnl_mismatches"]) == 1
    assert report["learning_missing_or_mismatched"] == ["decision-active"]
    assert report["accounting_issues"] == ["equity_cash_positions_unrealized_mismatch", "pending_authorized_executions"]


def test_matching_cash_and_equity_cannot_hide_account_reset(tmp_path):
    db = history(tmp_path)
    before = capture(db, scope="active")
    state = db.get_json("autonomous_paper_state", "active")["value"]
    db.put_json("autonomous_paper_state", "active", {**state, "cash": 100., "equity": 100.})
    after = capture(db, scope="active")
    assert after["accounting_issues"] == []
    assert compare(before, after)["history_preserved"] is True
    assert compare(before, after)["cash_reconciled"] is False
