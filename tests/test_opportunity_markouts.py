from __future__ import annotations

import copy
import json

import pytest

from learning_engine.opportunity_markouts import fixed_horizon_markouts

START = 1_700_000_000_000


def row(name, offset=0, *, proposal=True, symbol="BNBUSDT", **updates):
    return {"opportunity_id": name, "scope": "paper-a", "symbol": symbol,
        "decision_time_ms": START + offset, "recorded_at_ms": START + offset + 1,
        "proposal_present": proposal, "market_verified": True,
        "quote": {"bid_price": 99.9, "ask_price": 100.1, "received_at_unix_ms": START + offset},
        "cost_model": {"fee_rate": .001, "slippage_bps": 2},
        "council": {"opinions": [{"agent_id": "market_intelligence", "action": "BUY", "data_verified": True}]},
        "decision_quality": {"decision_quality_action": "BUY"},
        "result": {"status": "WAIT"}, **updates}


def diagnose(rows, *, cutoff=START + 30_000, horizons=(1,)):
    return fixed_horizon_markouts(rows, cutoff_ms=cutoff, horizons_seconds=horizons)


def test_cash_equations_charge_spread_fee_and_slippage_once():
    entry = row("entry", cost_model={"fee_rate": .01, "slippage_bps": 100})
    entry["quote"].update(bid_price=99, ask_price=100)
    future = row("future", 1000, proposal=False)
    future["quote"].update(bid_price=110, ask_price=111)
    entry["edge"] = {"known_cost_components_percent": 999}  # Not charged again.
    before = copy.deepcopy([entry, future])
    r = diagnose([entry, future])["records"][0]
    assert r["status"] == "OBSERVED"
    cash = r["unit_cashflows"]
    assert cash["cash_paid"] == pytest.approx(100 * 1.01 * 1.01)
    assert cash["cash_received"] == pytest.approx(110 * .99 * .99)
    assert r["long_markout_percent_excluding_impact"] == pytest.approx(100 * (107.811 / 102.01 - 1))
    assert r["bbo_long_markout_percent_before_fees_slippage"] == pytest.approx(10)
    assert cash["market_impact"] is r["complete_net_return_percent"] is None
    assert [entry, future] == before


def test_fee_and_slippage_assumptions_are_frozen_at_entry():
    entry, future = row("entry"), row("future", 1000, proposal=False)
    expected = diagnose([entry, future])
    future["cost_model"] = {"fee_rate": .95, "slippage_bps": 9000}
    actual = diagnose([entry, future])
    assert expected["records"] == actual["records"]
    assert expected["source_sha256"] != actual["source_sha256"]


def test_right_direction_is_not_economic_edge_and_sell_is_not_a_short():
    entry, future = row("entry"), row("future", 1000, proposal=False)
    entry["council"]["opinions"].append({"agent_id": "finance_ai", "action": "SELL", "data_verified": True})
    future["quote"].update(bid_price=99.91, ask_price=100.11)
    report = diagnose([entry, future])
    s = report["horizons"]["1"]["signals"]
    assert s["market_intelligence"]["direction_hit_rate"] == 1
    assert s["market_intelligence"]["buy_mean_long_markout_percent_excluding_impact"] < 0
    assert s["finance_ai"]["direction_hit_rate"] == 0
    assert s["finance_ai"]["buy_labels"] == 0
    assert s["finance_ai"]["sell_executable_return_percent"] is None
    assert s["finance_ai"]["buy_mean_long_markout_percent_excluding_impact"] is None
    assert report["records"][0]["actual_paper_status"] == "WAIT"
    assert report["execution_authority"] is False
    assert report["policy_influence"] == "NONE"
    assert report["profitability_evidence"] == "INSUFFICIENT_EVIDENCE"
    assert report["horizons"]["1"]["portfolio_net_expectancy"] is None


@pytest.mark.parametrize("change", ["unverified", "stale", "future", "crossed", "missing", "zero", "bool"])
def test_invalid_entry_quotes_remain_missing_anchors(change):
    entry, replacement, future = row("entry"), row("replacement", 20), row("future", 1000, proposal=False)
    if change == "unverified":
        entry["market_verified"] = False
    elif change in {"stale", "future"}:
        entry["quote"]["received_at_unix_ms"] = START - 2001 if change == "stale" else START + 1
    elif change == "crossed":
        entry["quote"]["bid_price"] = 101
    elif change == "missing":
        entry["quote"] = None
    else:
        entry["quote"]["bid_price"] = 0 if change == "zero" else True
    records = diagnose([entry, replacement, future])["records"]
    assert len(records) == 1 and records[0]["opportunity_id"] == "entry"
    assert records[0]["status"] == "INVALID_ENTRY_QUOTE"


@pytest.mark.parametrize("cost", [None, {}, {"fee_rate": -1, "slippage_bps": 2},
    {"fee_rate": True, "slippage_bps": 2}, {"fee_rate": .001, "slippage_bps": None},
    {"fee_rate": .001, "slippage_bps": 10_000}])
def test_unknown_or_invalid_cost_does_not_become_zero(cost):
    r = diagnose([row("entry", cost_model=cost), row("future", 1000, proposal=False)])
    assert r["records"][0]["status"] == "ENTRY_COST_UNAVAILABLE"
    assert r["horizons"]["1"]["cash_only_reference_markout_percent"] is None


@pytest.mark.parametrize("change", ["late_persistence", "wrong_symbol", "wrong_scope", "unverified", "stale", "outside_tolerance"])
def test_future_quote_must_have_matching_identity_freshness_and_availability(change):
    entry, future = row("entry"), row("future", 1000, proposal=False)
    if change == "late_persistence":
        future["recorded_at_ms"] = START + 30_001
    elif change == "wrong_symbol":
        future["symbol"] = "SOLUSDT"
    elif change == "wrong_scope":
        future["scope"] = "paper-b"
    elif change == "unverified":
        future["market_verified"] = False
    elif change == "stale":
        future["quote"]["received_at_unix_ms"] -= 2001
    else:
        future = row("future", 11_001, proposal=False)
    result = diagnose([entry, future])
    assert result["records"][0]["status"] == "MISSING_FUTURE_QUOTE"


def test_cutoff_not_elapsed_and_first_quote_not_best_return():
    entry, first, better = row("entry"), row("first", 1000, proposal=False), row("better", 1001, proposal=False)
    better["quote"].update(bid_price=200, ask_price=201)
    assert diagnose([entry, first, better], cutoff=START+500)["records"][0]["status"] == "HORIZON_NOT_ELAPSED"
    actual = diagnose([better, entry, first])["records"][0]
    assert actual["label_opportunity_id"] == "first"
    assert actual["label_available_at_ms"] == START+1001
    assert actual["long_markout_percent_excluding_impact"] < 0
    # Exact ten-second label tolerance is accepted, never interpolated.
    assert diagnose([entry, row("edge", 11_000, proposal=False)])["records"][0]["status"] == "OBSERVED"


def test_anchor_selection_precedes_label_existence_and_is_per_symbol():
    rows = [row("missing"), row("would_have_label", 500),
            row("too_late_for_first", 11_001, proposal=False),
            row("next_anchor", 11_002), row("next_label", 12_002, proposal=False),
            row("other_symbol", symbol="SOLUSDT"), row("other_label", 1000, proposal=False, symbol="SOLUSDT")]
    report = diagnose(rows)
    selected = {r["opportunity_id"]: r for r in report["records"]}
    assert set(selected) == {"missing", "next_anchor", "other_symbol"}
    assert selected["missing"]["status"] == "MISSING_FUTURE_QUOTE"
    assert selected["next_anchor"]["status"] == selected["other_symbol"]["status"] == "OBSERVED"
    assert report["records"] == diagnose(list(reversed(rows)))["records"]
    assert report["horizons"]["1"]["independent_sample_size"] is None


def test_unavailable_or_non_directional_members_are_not_added_as_wait_votes():
    entry = row("entry")
    entry["council"]["opinions"] += [
        {"agent_id": "unverified", "action": "BUY", "data_verified": False},
        {"agent_id": "risk_engine", "action": "SELL", "data_verified": True}]
    s = diagnose([entry, row("future", 1000, proposal=False)])["records"][0]["signals"]
    assert "unverified" not in s and "risk_engine" not in s
    assert s["EQUAL_WEIGHT_DIRECTION"] == "BUY"


@pytest.mark.parametrize("change", ["duplicate", "scope", "timestamp", "persistence", "horizon"])
def test_invalid_dataset_identity_and_chronology_fail_explicitly(change):
    rows = [row("entry")]
    if change == "duplicate":
        rows += copy.deepcopy(rows)
    elif change == "scope":
        rows[0]["scope"] = ""
    elif change == "timestamp":
        rows[0]["decision_time_ms"] = True
    elif change == "persistence":
        rows[0]["recorded_at_ms"] = START-1
    with pytest.raises(ValueError):
        diagnose(rows, horizons=(True,) if change == "horizon" else (1,))


def test_empty_source_and_unmatured_window_do_not_claim_performance():
    empty = diagnose([])
    assert empty["horizons"]["1"]["selected_anchors"] == 0
    assert empty["horizons"]["1"]["cash_only_reference_markout_percent"] is None
    assert empty["horizons"]["1"]["profit_factor"] is None
    json.dumps(empty, allow_nan=False)


def test_cli_preserves_previous_evidence_and_uses_explicit_cutoff(tmp_path, monkeypatch, capsys):
    from scripts.paper_opportunity_markouts import main
    source, output = tmp_path / "source.json", tmp_path / "result.json"
    source.write_text(json.dumps([row("entry"), row("future", 300_000, proposal=False)]))
    monkeypatch.setattr("sys.argv", ["markouts", "--source", str(source), "--output", str(output),
                                    "--cutoff-ms", str(START+300_001)])
    main()
    result = output.read_bytes()
    assert json.loads(result)["horizons"]["300"]["coverage"] == {"OBSERVED": 1}
    with pytest.raises(SystemExit):
        main()
    assert output.read_bytes() == result
    assert "output exists" in capsys.readouterr().err


def test_all_opportunities_retains_wait_and_does_not_fabricate_council_votes():
    wait = row("wait", proposal=False, council=None, decision_quality=None)
    future = row("label", 1000, proposal=False)
    original = copy.deepcopy([wait, future])
    assert diagnose(original)["records"] == []
    report = fixed_horizon_markouts(original, cutoff_ms=START+30_000,
                                   horizons_seconds=(1,), anchor_population="all_opportunities")
    record = report["records"][0]
    assert record["opportunity_id"] == "wait" and record["proposal_present"] is False
    assert record["signals"] == {} and record["actual_paper_status"] == "WAIT"
    group = report["abstention_diagnostics"]["1"]["groups"][0]
    assert group["population"] == "no_proposal" and group["observed_labels"] == 1
    assert group["mean_long_markout_percent_excluding_impact"] < 0
    assert group["portfolio_counterfactual_net_pnl"] is None
    assert report["execution_authority"] is False
    assert [wait, future] == original


def test_no_proposal_missing_quote_reserves_interval_before_better_candidate():
    rows = [row("missing", proposal=False, quote=None), row("better", 1),
            row("label", 1000, proposal=False), row("next", 11_001, proposal=False),
            row("next_label", 12_001, proposal=False)]
    report = fixed_horizon_markouts(rows, cutoff_ms=START+30_000,
                                   horizons_seconds=(1,), anchor_population="all_opportunities")
    assert [r["opportunity_id"] for r in report["records"]] == ["missing", "next"]
    assert [r["status"] for r in report["records"]] == ["INVALID_ENTRY_QUOTE", "OBSERVED"]
    group = report["abstention_diagnostics"]["1"]["groups"][0]
    assert group["selected_anchors"] == 2 and group["observed_labels"] == 1


def test_all_population_cannot_use_late_persistence_or_unknown_proposal_as_false():
    rows = [row("unknown", proposal=None), row("late", 1000, proposal=False)]
    rows[1]["recorded_at_ms"] = START+30_001
    report = fixed_horizon_markouts(rows, cutoff_ms=START+30_000,
                                   horizons_seconds=(1,), anchor_population="all_opportunities")
    group = report["abstention_diagnostics"]["1"]["groups"][0]
    assert group["population"] == "proposal_status_unknown"
    assert group["coverage"] == {"MISSING_FUTURE_QUOTE": 1}
    assert group["mean_long_markout_percent_excluding_impact"] is None
    assert group["positive_long_markouts"] is None


def test_population_selection_is_explicit_and_default_output_is_identical():
    rows = [row("wait", proposal=False), row("proposal", 1), row("label", 1001, proposal=False)]
    assert fixed_horizon_markouts(rows, cutoff_ms=START+30_000, horizons_seconds=(1,),
                                 anchor_population="proposals") == diagnose(rows)
    with pytest.raises(ValueError, match="anchor_population"):
        fixed_horizon_markouts(rows, cutoff_ms=START+30_000, anchor_population="profitable_only")


def test_cli_explicit_all_population_reports_no_proposal_actions(tmp_path, monkeypatch):
    from scripts.paper_opportunity_markouts import main
    source, output = tmp_path / "source.json", tmp_path / "result.json"
    source.write_text(json.dumps([row("wait", proposal=False, council=None, decision_quality=None),
                                  row("label", 300_000, proposal=False)]))
    monkeypatch.setattr("sys.argv", ["markouts", "--source", str(source), "--output", str(output),
        "--cutoff-ms", str(START+300_001), "--anchor-population", "all_opportunities"])
    main()
    report = json.loads(output.read_text())
    assert report["anchor_population"] == "all_opportunities"
    assert report["abstention_diagnostics"]["300"]["groups"][0]["population"] == "no_proposal"
