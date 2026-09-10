from __future__ import annotations

import copy

import pytest

from learning_engine.paper_economic_shadow import UNKNOWN_EPOCH, assess_opportunity, digest, read_sources
from storage import ProjectDatabase

START = 1_700_000_000_000
SHA = "a" * 40
POLICY = "paper-post-stop-v1:observe"


def opportunity(**updates):
    return {"scope": "scope-a", "symbol": "BNBUSDT", "decision_time_ms": START + 5000,
        "paper_build_sha": SHA, "paper_strategy_version": POLICY, "regime": "bull",
        "market_verified": True, "quote": {"bid_price": 99.9, "ask_price": 100.1,
            "received_at_unix_ms": START + 4990},
        "cost_model": {"fee_rate": 0.001, "slippage_bps": 2}, **updates}


def sources(*, pnl=-1.199, outcome_stored=START + 3000):
    buy = {"decision_id": "b1", "trade_id": "buy1", "symbol": "BNBUSDT", "side": "BUY",
        "price": 100, "quantity": 1, "fee": 0.1, "created_at_ms": START + 1000,
        "verified_market_data": True, "paper_build_sha": SHA, "paper_strategy_version": POLICY}
    sell = {**buy, "trade_id": "sell1", "side": "SELL", "price": 99, "fee": 0.099,
        "created_at_ms": START + 2000, "net_pnl": pnl, "reason": "protective_stop_loss",
        # These costs are already reflected in fill prices; never subtract again.
        "spread_cost": 0.04, "slippage_cost": 0.03, "impact_cost": 0.01}
    outcome = {"decision_id": "b1", "outcome_id": "paper:b1", "source": "paper",
        "evidence_schema_version": 2, "net_pnl": pnl, "regime": "bull",
        "occurred_at_ms": START + 2000, "evidence_available_at_ms": START + 2500,
        "verified_market_data": True, "realized_action": None}
    return {"coverage": "COMPLETE_SNAPSHOT",
        "trades": [{"value": buy, "stored_at_ms": START + 1001},
                   {"value": sell, "stored_at_ms": START + 2001}],
        "outcomes": {"paper:b1": {"value": outcome, "stored_at_ms": outcome_stored}},
        "epochs": [{"value": {"scope": "scope-a", "epoch_id": "epoch-1", "sha": SHA,
            "strategy_version": POLICY, "epoch_start_ms": START}, "stored_at_ms": START + 1}]}


def test_outcome_changes_future_shadow_context_but_never_becomes_a_forecast():
    data = sources()
    before = digest(data)
    early = assess_opportunity(opportunity(decision_time_ms=START + 2900), data)
    late = assess_opportunity(opportunity(), data)
    assert early["learning_context"]["cohort"]["sample_size"] == 0
    assert late["learning_context"]["cohort"]["sample_size"] == 1
    assert late["learning_context"]["recent_failed_hypothesis"]["decision_id"] == "b1"
    stats = late["learning_context"]["cohort"]
    assert stats["historical_net_expectancy_usdt"] == pytest.approx(-1.199)
    assert stats["historical_gross_fill_expectancy_usdt"] == -1
    assert stats["mean_pair_fees_usdt"] == pytest.approx(0.199)
    assert stats["historical_mean_net_return_percent"] == pytest.approx(-1.199)
    assert late["edge"]["expected_net_edge_percent"] is None
    assert late["edge"]["expected_gross_return_percent"] is None
    assert late["edge"]["expected_cost_percent"] is None  # Impact is not known.
    assert late["edge"]["known_cost_components_percent"] == pytest.approx(0.44)
    assert late["learning_context"]["confidence_adjustment"] is None
    assert late["execution_authority"] is late["live_policy_changed"] is False
    assert before == digest(data)


@pytest.mark.parametrize("boundary", ["settlement", "availability", "ingestion", "buy_commit", "sell_commit"])
def test_every_future_information_boundary_is_excluded(boundary):
    data = sources()
    if boundary == "settlement":
        data["trades"][1]["value"]["created_at_ms"] = START + 5000
        data["outcomes"]["paper:b1"]["value"].update(occurred_at_ms=START + 5000, evidence_available_at_ms=START + 5000)
    elif boundary == "availability":
        data["outcomes"]["paper:b1"]["value"]["evidence_available_at_ms"] = START + 5000
    elif boundary == "ingestion":
        data["outcomes"]["paper:b1"]["stored_at_ms"] = START + 5000
    else:
        data["trades"][0 if boundary == "buy_commit" else 1]["stored_at_ms"] = START + 5000
    result = assess_opportunity(opportunity(), data)
    assert result["learning_context"]["cohort"]["sample_size"] == 0
    assert result["learning_context"]["recent_failed_hypothesis"] is None


@pytest.mark.parametrize("change", ["epoch", "unknown_epoch", "regime", "unknown_regime", "scope", "later_registration"])
def test_legacy_carry_in_regime_and_scope_are_not_current_support(change):
    data = sources()
    op = opportunity()
    if change == "epoch":
        data["epochs"].append({"value": {**data["epochs"][0]["value"], "epoch_id": "epoch-2",
            "epoch_start_ms": START + 4000}, "stored_at_ms": START + 4000})
    elif change == "unknown_epoch":
        data["trades"][0]["value"].pop("paper_build_sha")
    elif change in {"regime", "unknown_regime"}:
        op["regime"] = "range" if change == "regime" else "unknown"
    elif change == "scope":
        data["epochs"][0]["value"]["scope"] = "scope-b"
    else:
        data["epochs"][0]["stored_at_ms"] = START + 5000
    result = assess_opportunity(op, data)
    assert result["learning_context"]["cohort"]["sample_size"] == 0
    # Prior failure remains evidence, never a fabricated new-epoch return.
    assert result["learning_context"]["recent_failed_hypothesis"] is not None


@pytest.mark.parametrize("change", ["unverified", "pnl", "learning_pnl", "quantity", "ambiguous", "source"])
def test_bad_evidence_cannot_enter_learning_stats(change):
    data = sources()
    if change == "unverified":
        data["trades"][0]["value"]["verified_market_data"] = False
    elif change == "pnl":
        data["trades"][1]["value"]["net_pnl"] = 10
    elif change == "learning_pnl":
        data["outcomes"]["paper:b1"]["value"]["net_pnl"] = 10
    elif change == "quantity":
        data["trades"][1]["value"]["quantity"] = 2
    elif change == "source":
        data["outcomes"]["paper:b1"]["value"]["source"] = "testnet"
    else:
        data["trades"].append(copy.deepcopy(data["trades"][1]))
    result = assess_opportunity(opportunity(), data)
    assert result["learning_context"]["cohort"]["sample_size"] == 0
    assert sum(result["excluded_counts"].values()) == 1


@pytest.mark.parametrize("quote", [None, {}, {"bid_price": 100, "ask_price": 99},
    {"bid_price": 99, "ask_price": 100, "received_at_unix_ms": START},
    {"bid_price": 99, "ask_price": 100, "received_at_unix_ms": START + 5001}])
def test_missing_stale_future_or_invalid_bbo_has_no_numeric_cost(quote):
    result = assess_opportunity(opportunity(quote=quote), sources())
    assert result["edge"]["known_cost_components_percent"] is None


def test_database_scope_filter_and_source_cap_are_explicit(tmp_path, monkeypatch):
    db = ProjectDatabase(f"sqlite:///{tmp_path / 'evidence.db'}")
    db.initialize()
    db.put_json("paper_trades:scope-b", "other", {"symbol": "BNBUSDT"})
    assert read_sources(db, "scope-a")["trades"] == []
    for n in range(3):
        db.put_json("paper_trades:scope-a", str(n), {"symbol": "BNBUSDT"})
    monkeypatch.setattr("learning_engine.paper_economic_shadow.SOURCE_LIMIT", 2)
    data = read_sources(db, "scope-a")
    assert data["coverage"] == "SOURCE_LIMIT_EXCEEDED"
    assert data["trades"] == []
    assert assess_opportunity(opportunity(), data)["strategy_epoch_id"] == UNKNOWN_EPOCH
