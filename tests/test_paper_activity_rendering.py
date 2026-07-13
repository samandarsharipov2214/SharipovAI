from __future__ import annotations

from dashboard.paper_activity_api import _format_time, _money, _price, _render


def test_virtual_account_rendering_helpers_are_total() -> None:
    assert _money(1234.56) == "1 234.6"
    assert _money(None) == "—"
    assert _price(65000.123) == "65 000.1"
    assert _price("bad") == "—"
    assert _format_time(0) == "—"
    assert _format_time("bad") == "—"


def test_virtual_account_page_renders_trade_without_name_errors() -> None:
    html = _render(
        {
            "summary": {
                "trade_count": 1,
                "buy_count": 1,
                "sell_count": 0,
                "open_positions": 1,
                "closed_positions": 0,
                "win_rate_percent": 0,
                "equity": 9999.8,
                "net_pnl": -0.2,
                "total_fees": 0.1,
                "last_tick_at": 1_700_000_000,
                "last_reason_ru": "виртуальная сделка открыта",
            },
            "trades": [
                {
                    "id": "VA-1",
                    "symbol": "BTC/USDT",
                    "side": "BUY",
                    "status": "OPEN",
                    "opened_at": 1_700_000_000,
                    "entry_price": 65_000,
                    "current_price": 65_100,
                    "net_pnl": 0.05,
                    "fee": 0.1,
                    "entry_reason_ru": "подтверждённый виртуальный сигнал",
                    "real_order_placed": False,
                    "quote_source": "Bybit public market data",
                }
            ],
        },
        {"status": "running"},
    )

    assert "VA-1" in html
    assert "BTC/USDT" in html
    assert "BUY · покупка" in html
    assert "Bybit public market data" in html
    assert "Real orders</small><b>blocked" in html
