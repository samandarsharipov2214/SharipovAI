from __future__ import annotations

from scripts.astra_paper_diagnose import collect
from storage import ProjectDatabase


def test_diagnosis_reports_machine_readable_current_wait_reasons(tmp_path):
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'diagnosis.sqlite3'}")
    database.initialize()
    database.put_json("council_decision_trace", "BTCUSDT", {
        "symbol": "BTCUSDT", "updated_at_ms": 100, "status": "WAIT",
        "reason": "24h change is inside entry threshold", "authorized": True,
        "candidate_validation_valid": True, "market_verified": True,
    })
    database.put_json("council_decision_trace", "BNBUSDT", {
        "symbol": "BNBUSDT", "updated_at_ms": 101, "status": "WAIT",
        "reason": "mandatory gate BLOCK: risk_engine=insufficient_verified_liquidity",
        "risk_blocks": ["insufficient_verified_liquidity"],
    })
    database.put_json("council_decision_trace", "XRPUSDT", {
        "symbol": "XRPUSDT", "updated_at_ms": 102, "status": "BLOCK",
        "reason": "verified quote is not time-aligned with REST BBO",
    })
    database.put_json("paper_v2_decisions", "paper-btc", {
        "candidate_side": "Buy", "controller": {"final_intent": "BUY"},
    })
    database.put_json("council_decision_trace", "BTCUSDT", {
        "symbol": "BTCUSDT", "updated_at_ms": 103, "status": "WAIT", "decision_id": "paper-btc",
        "reason": "24h change is inside entry threshold", "authorized": True,
        "candidate_validation_valid": True, "market_verified": True,
    })
    result = collect(database)
    assert result["status"] == "VERIFIED" and result["read_only"] is True
    reasons = {row["symbol"]: row["reason_code"] for row in result["symbols"]}
    assert reasons == {"BNBUSDT": "RISK_INSUFFICIENT_LIQUIDITY", "BTCUSDT": "NO_ENTRY_SIGNAL",
                       "XRPUSDT": "QUOTE_LINEAGE_REJECTED"}
    btc = next(row for row in result["symbols"] if row["symbol"] == "BTCUSDT")
    assert btc["candidate_side"] == "Buy" and btc["controller_final_intent"] == "BUY"


def test_diagnosis_does_not_misclassify_anti_churn_as_stale_market_data(tmp_path):
    database = ProjectDatabase(f"sqlite:///{tmp_path / 'diagnosis.sqlite3'}")
    database.initialize()
    database.put_json("council_decision_trace", "XRPUSDT", {
        "symbol": "XRPUSDT", "updated_at_ms": 100, "status": "WAIT",
        "quote_age_ms": 1500, "market_verified": True,
        "reason": "anti_churn_cost_not_covered: prospective_edge_unavailable; forecast_not_promoted",
    })
    result = collect(database)
    assert result["symbols"][0]["reason_code"] == "PROSPECTIVE_EDGE_UNAVAILABLE"
