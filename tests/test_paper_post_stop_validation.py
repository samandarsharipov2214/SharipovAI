import copy

import pytest

from risk_engine.paper_reentry import PAPER_POST_STOP_COOLDOWN_MS
from tools.paper_post_stop_validation import screen_trades


def _trade(side, stamp, decision, *, reason="canonical_council_allow", net=None):
    return {"trade_id": f"{side}-{stamp}", "symbol": "BNBUSDT", "side": side,
            "created_at_ms": stamp, "decision_id": decision, "reason": reason,
            "price": 10, "quantity": 1, "notional": 10, "fee": 0.01,
            "net_pnl": net, "verified_market_data": True}


def test_screen_uses_only_prior_closes_and_retains_losing_evidence():
    start = 1_700_000_000_000
    rows = [_trade("BUY", start, "a"),
            _trade("SELL", start + 1, "a", reason="protective_stop_loss", net=-1),
            _trade("BUY", start + 2, "b"),
            _trade("SELL", start + 3, "b", reason="protective_take_profit", net=2),
            _trade("BUY", start + 4 + PAPER_POST_STOP_COOLDOWN_MS, "c"),
            _trade("SELL", start + 5 + PAPER_POST_STOP_COOLDOWN_MS, "c", reason="canonical_council_sell:c", net=-1)]
    original = copy.deepcopy(rows)
    result = screen_trades(list(reversed(rows)), epoch_start_ms=start)
    full = result["comparisons"]["full"]
    # Removing a WIN worsens this screen: no winning-window/losing-trade filter.
    assert set(result["blocked_entry_reasons"]) == {"b"}
    assert full["0"]["baseline_pairs"]["closed_pairs"] == 3
    assert full["0"]["candidate_retained_pairs"]["net_pnl_of_pairs"] == -2
    assert full["10"]["candidate_retained_pairs"]["net_pnl_of_pairs"] == pytest.approx(-2.04)
    assert full["0"]["candidate_retained_pairs"]["candidate_portfolio_drawdown"] is None
    assert result["profitability_evidence"] == "INSUFFICIENT_EVIDENCE"
    assert result["untouched_holdout"] is False
    assert rows == original
    assert result == screen_trades(rows, epoch_start_ms=start)


def test_future_stop_cannot_retroactively_block_entry():
    rows = [_trade("BUY", 100, "a"), _trade("SELL", 200, "a", reason="protective_stop_loss", net=-1)]
    assert screen_trades(rows, epoch_start_ms=100)["blocked_entry_reasons"] == {}


@pytest.mark.parametrize("kind", ["unverified", "duplicate", "future_entry", "nan"])
def test_unsupported_evidence_is_rejected(kind):
    rows = [_trade("BUY", 100, "a"), _trade("SELL", 200, "a", reason="protective_stop_loss", net=-1)]
    if kind == "unverified": rows[0]["verified_market_data"] = False
    if kind == "duplicate": rows.append(copy.deepcopy(rows[0]))
    if kind == "future_entry": rows[0]["created_at_ms"] = 300
    if kind == "nan": rows[1]["net_pnl"] = float("nan")
    with pytest.raises(ValueError):
        screen_trades(rows, epoch_start_ms=100)
