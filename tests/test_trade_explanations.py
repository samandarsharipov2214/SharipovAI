from dashboard.trade_explanations import enrich_tick_result, enrich_virtual_state, explain_trade


def test_explain_sell_trade_from_24h_signal() -> None:
    trade = {
        "symbol": "SOL/USDT",
        "side": "SELL",
        "status": "OPEN",
        "signal_change_24h_percent": -2.125,
        "quote_source": "bybit",
    }
    explain_trade(trade)
    assert "Продажа SOL/USDT" in trade["entry_reason_ru"]
    assert "-2.125%" in trade["entry_reason_ru"]
    assert "0.35%" in trade["entry_reason_ru"]
    assert "Позиция ещё открыта" in trade["operation_explanation_ru"]


def test_explain_closed_buy_trade() -> None:
    trade = {
        "symbol": "BTC/USDT",
        "side": "BUY",
        "status": "CLOSED",
        "signal_change_24h_percent": 1.5,
        "close_reason": "take_profit",
    }
    explain_trade(trade)
    assert "Покупка BTC/USDT" in trade["entry_reason_ru"]
    assert trade["close_reason_ru"] == "достигнута цель прибыли"
    assert "Закрытие" in trade["operation_explanation_ru"]


def test_enrich_existing_state_and_tick_payload() -> None:
    state = {
        "trades": [
            {
                "symbol": "XRP/USDT",
                "side": "SELL",
                "status": "CLOSED",
                "signal_change_24h_percent": -0.8,
                "close_reason_ru": "сработал лимит убытка",
            }
        ]
    }
    enriched = enrich_virtual_state(state)
    assert enriched["trades"][0]["entry_reason_ru"]
    result = enrich_tick_result({"status": "ok", "state": state})
    assert result["state"]["trades"][0]["operation_explanation_ru"]
