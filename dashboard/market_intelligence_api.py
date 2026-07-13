"""Market Intelligence API for SharipovAI.

This module adds three analytical capabilities without changing the live or
virtual execution state:

* a ranked multi-asset screener;
* actionable in-app alerts;
* a conservative historical replay of the current baseline strategy.

Public Bybit market data is used for calculations. No endpoint in this module
places an exchange order or mutates the virtual account.
"""
from __future__ import annotations

import asyncio
import math
import os
import statistics
import time
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import FastAPI, Query

from market_paper_engine import PaperActivityEngine

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT")
INTERVALS = {"1": 60, "5": 300, "15": 900, "60": 3600, "240": 14_400, "D": 86_400}
BYBIT_PUBLIC_API_BASE = os.getenv("BYBIT_PUBLIC_API_BASE", "https://api.bybit.com").rstrip("/")
FEE_RATE = 0.001
DEFAULT_NOTIONAL = 100.0
STARTING_EQUITY = 10_000.0
MIN_ABS_CHANGE_PERCENT = 0.35
TAKE_PROFIT_PERCENT = 1.2
STOP_LOSS_PERCENT = 0.8
MAX_HOLD_SECONDS = 60 * 60
SNAPSHOT_TTL_SECONDS = 20.0
CANDLE_TTL_SECONDS = 30.0

_CACHE: dict[str, tuple[float, Any]] = {}
_CACHE_LOCK = asyncio.Lock()


def install_market_intelligence_api(app: FastAPI) -> None:
    """Install market intelligence endpoints exactly once."""

    if getattr(app.state, "market_intelligence_api_installed", False):
        return
    app.state.market_intelligence_api_installed = True

    @app.get("/api/market-intelligence/snapshot", response_model=None)
    async def market_intelligence_snapshot() -> Any:
        return await get_market_snapshot()

    @app.get("/api/market-intelligence/replay", response_model=None)
    async def market_intelligence_replay(
        symbol: str = Query(default="BTCUSDT"),
        interval: str = Query(default="15"),
        limit: int = Query(default=500, ge=120, le=1000),
    ) -> Any:
        normalized_symbol = _normalize_symbol(symbol)
        normalized_interval = interval if interval in INTERVALS else "15"
        try:
            candles = await _get_candles(normalized_symbol, normalized_interval, limit)
            report = simulate_replay(candles, symbol=normalized_symbol, interval=normalized_interval)
            return {
                "status": "ok",
                "generated_at": _now_iso(),
                "source": "Bybit public historical candles",
                "analysis_only": True,
                "real_orders_placed": False,
                "virtual_account_modified": False,
                **report,
            }
        except Exception as exc:
            return {
                "status": "unavailable",
                "generated_at": _now_iso(),
                "symbol": normalized_symbol,
                "interval": normalized_interval,
                "analysis_only": True,
                "real_orders_placed": False,
                "virtual_account_modified": False,
                "error": f"{type(exc).__name__}: {exc}",
                "candles": [],
                "trades": [],
                "equity_curve": [],
                "summary": {},
            }


async def get_market_snapshot() -> dict[str, Any]:
    """Return a cached ranked screener plus actionable alerts."""

    async def factory() -> dict[str, Any]:
        generated_at = _now_iso()
        try:
            async with httpx.AsyncClient(timeout=8.0, headers={"User-Agent": "SharipovAI/market-intelligence"}) as client:
                ticker_payload = await _bybit_get(client, "/v5/market/tickers", {"category": "spot"})
                ticker_rows = ticker_payload.get("result", {}).get("list", [])
                ticker_map = {
                    str(item.get("symbol", "")).upper(): item
                    for item in ticker_rows
                    if isinstance(item, dict)
                }
                candle_results = await asyncio.gather(
                    *[_get_candles(symbol, "15", 160, client=client) for symbol in SYMBOLS],
                    return_exceptions=True,
                )
        except Exception as exc:
            alert = _alert(
                "critical",
                "market_source_unavailable",
                "Рыночный скринер временно недоступен",
                f"Bybit не вернул данные: {type(exc).__name__}: {exc}",
            )
            return {
                "status": "degraded",
                "generated_at": generated_at,
                "source": "Bybit public market data",
                "rows": [],
                "alerts": [alert],
                "summary": {"symbols_total": len(SYMBOLS), "symbols_ready": 0, "signals": 0, "high_risk": 0},
                "real_orders_blocked": True,
            }

        rows: list[dict[str, Any]] = []
        for symbol, candle_result in zip(SYMBOLS, candle_results, strict=True):
            ticker = ticker_map.get(symbol, {})
            if isinstance(candle_result, Exception):
                rows.append(
                    {
                        "symbol": symbol,
                        "status": "unavailable",
                        "score": 0.0,
                        "signal": "WAIT",
                        "signal_ru": "НЕТ ДАННЫХ",
                        "risk": "HIGH",
                        "risk_ru": "ВЫСОКИЙ",
                        "reason_ru": f"Свечи недоступны: {type(candle_result).__name__}",
                    }
                )
                continue
            try:
                rows.append(analyze_symbol(symbol, ticker, candle_result))
            except Exception as exc:
                rows.append(
                    {
                        "symbol": symbol,
                        "status": "unavailable",
                        "score": 0.0,
                        "signal": "WAIT",
                        "signal_ru": "НЕТ ДАННЫХ",
                        "risk": "HIGH",
                        "risk_ru": "ВЫСОКИЙ",
                        "reason_ru": f"Расчёт не выполнен: {type(exc).__name__}: {exc}",
                    }
                )

        rows.sort(key=lambda item: (str(item.get("status")) == "ready", float(item.get("score", 0.0))), reverse=True)
        virtual_state = await _safe_virtual_state()
        alerts = build_alerts(rows, virtual_state)
        ready = [row for row in rows if row.get("status") == "ready"]
        return {
            "status": "ok" if len(ready) == len(SYMBOLS) else "degraded",
            "generated_at": generated_at,
            "source": "Bybit public tickers and 15-minute candles",
            "method": "transparent_rule_based_ranking_v1",
            "rows": rows,
            "alerts": alerts,
            "summary": {
                "symbols_total": len(SYMBOLS),
                "symbols_ready": len(ready),
                "signals": sum(1 for row in ready if row.get("signal") in {"BUY", "SELL"}),
                "high_risk": sum(1 for row in ready if row.get("risk") == "HIGH"),
                "alerts": len(alerts),
                "critical_alerts": sum(1 for item in alerts if item.get("severity") == "critical"),
            },
            "real_orders_blocked": True,
            "disclaimer_ru": "Рейтинг помогает отбирать рынок для анализа, но не является обещанием прибыли.",
        }

    return await _cached("market-intelligence:snapshot", SNAPSHOT_TTL_SECONDS, factory)


async def _get_candles(
    symbol: str,
    interval: str,
    limit: int,
    *,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, float | int]]:
    symbol = _normalize_symbol(symbol)
    interval = interval if interval in INTERVALS else "15"
    limit = max(120, min(int(limit), 1000))
    key = f"candles:{symbol}:{interval}:{limit}"

    async def factory() -> list[dict[str, float | int]]:
        owns_client = client is None
        active_client = client or httpx.AsyncClient(timeout=8.0, headers={"User-Agent": "SharipovAI/market-intelligence"})
        try:
            payload = await _bybit_get(
                active_client,
                "/v5/market/kline",
                {"category": "spot", "symbol": symbol, "interval": interval, "limit": str(limit)},
            )
            raw_rows = payload.get("result", {}).get("list", [])
            candles = [_parse_kline(row) for row in raw_rows if isinstance(row, (list, tuple))]
            candles.sort(key=lambda item: int(item["time"]))
            if len(candles) < 30:
                raise RuntimeError(f"insufficient candles: {len(candles)}")
            return candles
        finally:
            if owns_client:
                await active_client.aclose()

    return await _cached(key, CANDLE_TTL_SECONDS, factory)


async def _bybit_get(client: httpx.AsyncClient, path: str, params: dict[str, str]) -> dict[str, Any]:
    response = await client.get(f"{BYBIT_PUBLIC_API_BASE}{path}", params=params)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("Bybit returned a non-object response")
    if int(payload.get("retCode", 0) or 0) != 0:
        raise RuntimeError(str(payload.get("retMsg", "Bybit API error")))
    return payload


async def _cached(key: str, ttl_seconds: float, factory: Callable[[], Awaitable[Any]]) -> Any:
    now = time.monotonic()
    cached = _CACHE.get(key)
    if cached and now - cached[0] < ttl_seconds:
        return cached[1]
    async with _CACHE_LOCK:
        now = time.monotonic()
        cached = _CACHE.get(key)
        if cached and now - cached[0] < ttl_seconds:
            return cached[1]
        value = await factory()
        _CACHE[key] = (time.monotonic(), value)
        return value


def analyze_symbol(symbol: str, ticker: dict[str, Any], candles: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Calculate transparent screener metrics for one symbol."""

    closes = [_float(item.get("close")) for item in candles]
    highs = [_float(item.get("high")) for item in candles]
    lows = [_float(item.get("low")) for item in candles]
    volumes = [_float(item.get("volume")) for item in candles]
    if len(closes) < 30 or any(value <= 0 for value in closes[-30:]):
        raise ValueError("not enough valid candle closes")

    price = _float(ticker.get("lastPrice"), closes[-1])
    change_24h = _float(ticker.get("price24hPcnt")) * 100.0
    if not ticker.get("price24hPcnt"):
        lookback = min(len(closes) - 1, 96)
        change_24h = ((closes[-1] / closes[-1 - lookback]) - 1.0) * 100.0
    bid = _float(ticker.get("bid1Price"))
    ask = _float(ticker.get("ask1Price"))
    spread_percent = ((ask - bid) / ((ask + bid) / 2.0) * 100.0) if bid > 0 and ask > 0 and ask >= bid else 0.0
    sma7 = statistics.fmean(closes[-7:])
    sma25 = statistics.fmean(closes[-25:])
    trend_percent = ((sma7 / sma25) - 1.0) * 100.0 if sma25 else 0.0
    rsi14 = _rsi(closes, 14)
    returns = [((closes[index] / closes[index - 1]) - 1.0) * 100.0 for index in range(max(1, len(closes) - 30), len(closes))]
    volatility = statistics.pstdev(returns) if len(returns) > 1 else 0.0
    atr_percent = _atr_percent(highs, lows, closes, 14)
    previous_volume = statistics.fmean(volumes[-21:-1]) if len(volumes) >= 21 else statistics.fmean(volumes[:-1])
    volume_ratio = volumes[-1] / previous_volume if previous_volume > 0 else 1.0
    turnover_24h = _float(ticker.get("turnover24h"))

    buy_setup = trend_percent > 0.04 and change_24h >= MIN_ABS_CHANGE_PERCENT and 48 <= rsi14 <= 76
    sell_setup = trend_percent < -0.04 and change_24h <= -MIN_ABS_CHANGE_PERCENT and 24 <= rsi14 <= 52
    signal = "BUY" if buy_setup else "SELL" if sell_setup else "WAIT"

    risk = "LOW"
    if spread_percent > 0.20 or volatility > 2.50 or atr_percent > 4.0 or rsi14 < 20 or rsi14 > 80:
        risk = "HIGH"
    elif spread_percent > 0.08 or volatility > 1.20 or atr_percent > 2.5 or rsi14 < 30 or rsi14 > 70:
        risk = "MEDIUM"

    score = 30.0
    score += min(abs(change_24h) * 4.0, 20.0)
    score += min(abs(trend_percent) * 10.0, 15.0)
    score += min(max(volume_ratio - 1.0, 0.0) * 12.0, 15.0)
    score += min(volatility * 3.0, 10.0)
    score += 10.0 if signal != "WAIT" else 0.0
    score -= min(spread_percent * 40.0, 15.0)
    score -= 12.0 if risk == "HIGH" else 4.0 if risk == "MEDIUM" else 0.0
    score = max(0.0, min(100.0, score))

    trend_ru = "ВОСХОДЯЩИЙ" if trend_percent > 0.04 else "НИСХОДЯЩИЙ" if trend_percent < -0.04 else "БОКОВОЙ"
    signal_ru = {"BUY": "ПОКУПКА", "SELL": "ПРОДАЖА", "WAIT": "НАБЛЮДАТЬ"}[signal]
    risk_ru = {"LOW": "НИЗКИЙ", "MEDIUM": "СРЕДНИЙ", "HIGH": "ВЫСОКИЙ"}[risk]
    reason_ru = (
        f"Тренд {trend_ru.lower()}: SMA7 {sma7:.4f}, SMA25 {sma25:.4f}; "
        f"изменение за 24ч {change_24h:+.2f}%; RSI {rsi14:.1f}; "
        f"объём последней свечи x{volume_ratio:.2f}; спред {spread_percent:.4f}%."
    )

    return {
        "symbol": symbol,
        "status": "ready",
        "price": round(price, 8),
        "change_24h_percent": round(change_24h, 4),
        "turnover_24h": round(turnover_24h, 2),
        "sma7": round(sma7, 8),
        "sma25": round(sma25, 8),
        "trend": "UP" if trend_percent > 0.04 else "DOWN" if trend_percent < -0.04 else "SIDEWAYS",
        "trend_ru": trend_ru,
        "trend_strength_percent": round(trend_percent, 4),
        "rsi14": round(rsi14, 2),
        "volatility_percent": round(volatility, 4),
        "atr_percent": round(atr_percent, 4),
        "volume_ratio": round(volume_ratio, 3),
        "spread_percent": round(spread_percent, 5),
        "signal": signal,
        "signal_ru": signal_ru,
        "risk": risk,
        "risk_ru": risk_ru,
        "score": round(score, 1),
        "reason_ru": reason_ru,
        "source": "Bybit public market data",
    }


def build_alerts(rows: Sequence[dict[str, Any]], virtual_state: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Build a compact alert list from screener results and open positions."""

    alerts: list[dict[str, Any]] = []
    ready = [row for row in rows if row.get("status") == "ready"]
    for row in rows:
        symbol = str(row.get("symbol", "MARKET"))
        if row.get("status") != "ready":
            alerts.append(_alert("critical", f"{symbol}:data", f"{symbol}: нет подтверждённых данных", str(row.get("reason_ru", "Источник недоступен")), symbol))
            continue
        change = abs(_float(row.get("change_24h_percent")))
        spread = _float(row.get("spread_percent"))
        volatility = _float(row.get("volatility_percent"))
        volume_ratio = _float(row.get("volume_ratio"), 1.0)
        if spread > 0.20:
            alerts.append(_alert("warning", f"{symbol}:spread", f"{symbol}: широкий спред", f"Спред {spread:.4f}% повышает стоимость входа и выхода.", symbol))
        if volatility > 2.50:
            alerts.append(_alert("warning", f"{symbol}:volatility", f"{symbol}: высокая волатильность", f"Волатильность 15-минутных свечей {volatility:.2f}% — риск повышен.", symbol))
        if change >= 5.0:
            alerts.append(_alert("warning", f"{symbol}:move", f"{symbol}: сильное движение за 24 часа", f"Цена изменилась на {_float(row.get('change_24h_percent')):+.2f}%.", symbol))
        if volume_ratio >= 2.5:
            alerts.append(_alert("info", f"{symbol}:volume", f"{symbol}: всплеск объёма", f"Последний объём в {volume_ratio:.2f} раза выше среднего.", symbol))

    for row in sorted(ready, key=lambda item: float(item.get("score", 0.0)), reverse=True)[:3]:
        if row.get("signal") in {"BUY", "SELL"}:
            alerts.append(
                _alert(
                    "info",
                    f"{row.get('symbol')}:signal",
                    f"{row.get('symbol')}: кандидат {row.get('signal_ru')}",
                    f"Оценка {row.get('score')}/100, риск {str(row.get('risk_ru')).lower()}. Это сигнал для анализа, а не приказ на сделку.",
                    str(row.get("symbol")),
                )
            )

    state = virtual_state or {}
    root = state.get("state") if isinstance(state.get("state"), dict) else state
    trades = root.get("trades", []) if isinstance(root, dict) else []
    now = int(time.time())
    for trade in trades if isinstance(trades, list) else []:
        if not isinstance(trade, dict) or str(trade.get("status", "")).upper() != "OPEN":
            continue
        symbol = str(trade.get("symbol", trade.get("asset", "POSITION"))).replace("/", "")
        entry = _float(trade.get("entry_price"))
        current = _float(trade.get("current_price"), entry)
        side = str(trade.get("side", "BUY")).upper()
        if entry <= 0 or current <= 0:
            continue
        move = ((current / entry) - 1.0) * 100.0 * (1.0 if side == "BUY" else -1.0)
        distance_tp = TAKE_PROFIT_PERCENT - move
        distance_sl = move + STOP_LOSS_PERCENT
        age = max(0, now - int(trade.get("opened_at", now) or now))
        if distance_sl <= 0.25:
            alerts.append(_alert("critical", f"{trade.get('id')}:sl", f"{symbol}: позиция рядом со стопом", f"До уровня стопа осталось примерно {max(0.0, distance_sl):.2f} п.п.", symbol))
        elif distance_tp <= 0.25:
            alerts.append(_alert("info", f"{trade.get('id')}:tp", f"{symbol}: позиция рядом с целью", f"До цели осталось примерно {max(0.0, distance_tp):.2f} п.п.", symbol))
        if age >= int(MAX_HOLD_SECONDS * 0.8):
            alerts.append(_alert("warning", f"{trade.get('id')}:age", f"{symbol}: позиция открыта долго", f"Прошло {age // 60} минут из лимита {MAX_HOLD_SECONDS // 60} минут.", symbol))

    severity_rank = {"critical": 0, "warning": 1, "info": 2}
    deduplicated: dict[str, dict[str, Any]] = {}
    for item in alerts:
        deduplicated[str(item["id"])] = item
    return sorted(deduplicated.values(), key=lambda item: (severity_rank.get(str(item.get("severity")), 9), str(item.get("symbol", ""))))[:30]


def simulate_replay(candles: Sequence[dict[str, Any]], *, symbol: str, interval: str) -> dict[str, Any]:
    """Replay a conservative version of the baseline strategy on historical bars."""

    ordered = sorted((dict(item) for item in candles), key=lambda item: int(item.get("time", 0)))
    if len(ordered) < 30:
        raise ValueError("Для воспроизведения нужно минимум 30 свечей")
    seconds_per_bar = INTERVALS.get(interval, 900)
    momentum_lookback = max(2, min(len(ordered) // 3, round(86_400 / seconds_per_bar)))
    max_hold_bars = max(1, math.ceil(MAX_HOLD_SECONDS / seconds_per_bar))
    cash = STARTING_EQUITY
    peak = cash
    max_drawdown = 0.0
    position: dict[str, Any] | None = None
    trades: list[dict[str, Any]] = []
    equity_curve: list[dict[str, Any]] = [{"time": int(ordered[0]["time"]), "equity": round(cash, 4)}]

    def close_position(index: int, exit_price: float, reason: str) -> None:
        nonlocal cash, peak, max_drawdown, position
        if position is None:
            return
        direction = 1.0 if position["side"] == "BUY" else -1.0
        quantity = position["quantity"]
        gross = direction * (exit_price - position["entry_price"]) * quantity
        exit_fee = exit_price * quantity * FEE_RATE
        fees = position["entry_fee"] + exit_fee
        net = gross - fees
        cash += net
        peak = max(peak, cash)
        drawdown = ((peak - cash) / peak * 100.0) if peak > 0 else 0.0
        max_drawdown = max(max_drawdown, drawdown)
        candle = ordered[index]
        trades.append(
            {
                "id": f"REPLAY-{len(trades) + 1}",
                "symbol": symbol,
                "side": position["side"],
                "opened_at": position["opened_at"],
                "closed_at": int(candle["time"]),
                "entry_index": position["entry_index"],
                "exit_index": index,
                "entry_price": round(position["entry_price"], 8),
                "exit_price": round(exit_price, 8),
                "notional": DEFAULT_NOTIONAL,
                "quantity": round(quantity, 12),
                "gross_pnl": round(gross, 4),
                "fees": round(fees, 4),
                "net_pnl": round(net, 4),
                "close_reason": reason,
                "close_reason_ru": {
                    "take_profit": "достигнута цель прибыли",
                    "stop_loss": "достигнут стоп",
                    "max_hold": "истёк максимальный срок позиции",
                    "end_of_replay": "закончился выбранный исторический отрезок",
                }.get(reason, reason),
                "signal_change_percent": round(position["signal_change_percent"], 4),
            }
        )
        equity_curve.append({"time": int(candle["time"]), "equity": round(cash, 4)})
        position = None

    for index in range(momentum_lookback, len(ordered)):
        candle = ordered[index]
        close = _float(candle.get("close"))
        high = _float(candle.get("high"), close)
        low = _float(candle.get("low"), close)
        if close <= 0:
            continue

        if position is not None and index > int(position["entry_index"]):
            entry = float(position["entry_price"])
            if position["side"] == "BUY":
                target = entry * (1.0 + TAKE_PROFIT_PERCENT / 100.0)
                stop = entry * (1.0 - STOP_LOSS_PERCENT / 100.0)
                hit_stop = low <= stop
                hit_target = high >= target
            else:
                target = entry * (1.0 - TAKE_PROFIT_PERCENT / 100.0)
                stop = entry * (1.0 + STOP_LOSS_PERCENT / 100.0)
                hit_stop = high >= stop
                hit_target = low <= target
            if hit_stop:
                close_position(index, stop, "stop_loss")
            elif hit_target:
                close_position(index, target, "take_profit")
            elif index - int(position["entry_index"]) >= max_hold_bars:
                close_position(index, close, "max_hold")

        if position is None and index < len(ordered) - 1:
            reference = _float(ordered[index - momentum_lookback].get("close"))
            if reference <= 0:
                continue
            momentum = ((close / reference) - 1.0) * 100.0
            if abs(momentum) >= MIN_ABS_CHANGE_PERCENT:
                side = "BUY" if momentum > 0 else "SELL"
                quantity = DEFAULT_NOTIONAL / close
                position = {
                    "side": side,
                    "entry_price": close,
                    "entry_index": index,
                    "opened_at": int(candle["time"]),
                    "quantity": quantity,
                    "entry_fee": DEFAULT_NOTIONAL * FEE_RATE,
                    "signal_change_percent": momentum,
                }

    if position is not None:
        close_position(len(ordered) - 1, _float(ordered[-1].get("close")), "end_of_replay")

    wins = [trade for trade in trades if float(trade["net_pnl"]) > 0]
    losses = [trade for trade in trades if float(trade["net_pnl"]) < 0]
    gross_profit = sum(float(trade["net_pnl"]) for trade in wins)
    gross_loss = abs(sum(float(trade["net_pnl"]) for trade in losses))
    total_fees = sum(float(trade["fees"]) for trade in trades)
    net_pnl = cash - STARTING_EQUITY
    summary = {
        "starting_equity": STARTING_EQUITY,
        "ending_equity": round(cash, 4),
        "net_pnl": round(net_pnl, 4),
        "return_percent": round(net_pnl / STARTING_EQUITY * 100.0, 4),
        "trade_count": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_percent": round((len(wins) / len(trades) * 100.0) if trades else 0.0, 2),
        "average_net_pnl": round((net_pnl / len(trades)) if trades else 0.0, 4),
        "profit_factor": round((gross_profit / gross_loss) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0), 3),
        "max_drawdown_percent": round(max_drawdown, 4),
        "total_fees": round(total_fees, 4),
        "buy_count": sum(1 for trade in trades if trade["side"] == "BUY"),
        "sell_count": sum(1 for trade in trades if trade["side"] == "SELL"),
    }
    return {
        "symbol": symbol,
        "interval": interval,
        "candle_count": len(ordered),
        "strategy": {
            "name": "verified_market_trend_baseline_replay_v1",
            "momentum_lookback_bars": momentum_lookback,
            "entry_threshold_percent": MIN_ABS_CHANGE_PERCENT,
            "take_profit_percent": TAKE_PROFIT_PERCENT,
            "stop_loss_percent": STOP_LOSS_PERCENT,
            "max_hold_bars": max_hold_bars,
            "fee_rate_each_side": FEE_RATE,
            "notional_per_trade": DEFAULT_NOTIONAL,
            "same_candle_conflict_policy": "stop_loss_first_conservative",
        },
        "summary": summary,
        "candles": ordered,
        "trades": trades,
        "equity_curve": equity_curve,
        "warning_ru": "Исторический результат не гарантирует будущую прибыль. Replay не изменяет виртуальный счёт.",
    }


async def _safe_virtual_state() -> dict[str, Any]:
    try:
        return await asyncio.to_thread(lambda: PaperActivityEngine().state(catch_up=False))
    except Exception:
        return {}


def _parse_kline(row: Sequence[Any]) -> dict[str, float | int]:
    if len(row) < 7:
        raise ValueError("invalid kline row")
    return {
        "time": int(float(row[0])),
        "open": float(row[1]),
        "high": float(row[2]),
        "low": float(row[3]),
        "close": float(row[4]),
        "volume": float(row[5]),
        "turnover": float(row[6]),
    }


def _rsi(closes: Sequence[float], period: int = 14) -> float:
    if len(closes) <= period:
        return 50.0
    changes = [closes[index] - closes[index - 1] for index in range(len(closes) - period, len(closes))]
    gains = [max(change, 0.0) for change in changes]
    losses = [max(-change, 0.0) for change in changes]
    average_gain = statistics.fmean(gains)
    average_loss = statistics.fmean(losses)
    if average_loss == 0:
        return 100.0 if average_gain > 0 else 50.0
    strength = average_gain / average_loss
    return 100.0 - (100.0 / (1.0 + strength))


def _atr_percent(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int = 14) -> float:
    start = max(1, len(closes) - period)
    ranges = [
        max(highs[index] - lows[index], abs(highs[index] - closes[index - 1]), abs(lows[index] - closes[index - 1]))
        for index in range(start, len(closes))
    ]
    if not ranges or closes[-1] <= 0:
        return 0.0
    return statistics.fmean(ranges) / closes[-1] * 100.0


def _alert(severity: str, alert_id: str, title: str, message: str, symbol: str = "SYSTEM") -> dict[str, Any]:
    return {
        "id": alert_id,
        "severity": severity,
        "symbol": symbol,
        "title": title,
        "message": message,
        "created_at": _now_iso(),
    }


def _normalize_symbol(symbol: str) -> str:
    normalized = "".join(character for character in str(symbol).upper() if character.isalnum())
    return normalized if normalized in SYMBOLS else "BTCUSDT"


def _float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else default
    except (TypeError, ValueError):
        return default


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
