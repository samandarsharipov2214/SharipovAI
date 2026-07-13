from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

from dashboard.market_intelligence_api import (
    analyze_symbol,
    build_alerts,
    install_market_intelligence_api,
    simulate_replay,
)

ROOT = Path(__file__).resolve().parents[1]
WEB2 = ROOT / "dashboard" / "static" / "web2"


def market_candles(count: int = 260) -> list[dict[str, float | int]]:
    rows: list[dict[str, float | int]] = []
    previous = 100.0
    for index in range(count):
        close = previous * (1.004 if index % 7 != 0 else 0.998)
        rows.append(
            {
                "time": 1_720_000_000_000 + index * 900_000,
                "open": previous,
                "high": max(previous, close) * 1.015,
                "low": min(previous, close) * 0.995,
                "close": close,
                "volume": 1000.0 + index * 7.0,
                "turnover": close * (1000.0 + index * 7.0),
            }
        )
        previous = close
    return rows


def test_routes_install_once():
    app = FastAPI()
    install_market_intelligence_api(app)
    install_market_intelligence_api(app)
    paths = [getattr(route, "path", "") for route in app.routes]
    assert paths.count("/api/market-intelligence/snapshot") == 1
    assert paths.count("/api/market-intelligence/replay") == 1


def test_screener_metrics_and_alerts_are_transparent():
    candles = market_candles(180)
    price = float(candles[-1]["close"])
    ticker = {
        "lastPrice": str(price),
        "price24hPcnt": "0.024",
        "turnover24h": "125000000",
        "bid1Price": str(price * 0.998),
        "ask1Price": str(price * 1.002),
    }
    row = analyze_symbol("BTCUSDT", ticker, candles)
    assert row["status"] == "ready"
    assert 0 <= row["score"] <= 100
    assert row["signal"] in {"BUY", "SELL", "WAIT"}
    assert row["risk"] in {"LOW", "MEDIUM", "HIGH"}
    assert row["volume_ratio"] > 0
    assert "SMA7" in row["reason_ru"]
    alerts = build_alerts([row], {})
    assert any(item["id"] == "BTCUSDT:spread" for item in alerts)


def test_replay_is_conservative_and_charges_fees():
    report = simulate_replay(market_candles(), symbol="BTCUSDT", interval="15")
    summary = report["summary"]
    assert report["strategy"]["same_candle_conflict_policy"] == "stop_loss_first_conservative"
    assert summary["trade_count"] > 0
    assert summary["total_fees"] > 0
    assert summary["ending_equity"] == round(summary["starting_equity"] + summary["net_pnl"], 4)
    assert summary["max_drawdown_percent"] >= 0
    assert all(trade["fees"] > 0 for trade in report["trades"])
    assert "не гарантирует" in report["warning_ru"]


def test_v33_interface_contains_all_three_tools():
    html = (WEB2 / "index.html").read_text(encoding="utf-8")
    script = (WEB2 / "market_intelligence_v33.js").read_text(encoding="utf-8")
    css = (WEB2 / "market_intelligence_v33.css").read_text(encoding="utf-8")
    assert "market_intelligence_v33.js?v=33" in html
    assert "market_intelligence_v33.css?v=33" in html
    assert "/api/market-intelligence/snapshot" in script
    assert "/api/market-intelligence/replay" in script
    assert "Умный скринер" in script
    assert "Оповещения" in script
    assert "Replay Lab" in script
    assert "не отправляет реальные ордера" in script
    assert ".mi33-table" in css
    assert "#mi33ReplayChart" in css
