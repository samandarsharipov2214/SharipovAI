"""Backend-only market data helpers for crypto analysis context."""
from __future__ import annotations

import asyncio
import re
import time
from collections import OrderedDict
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from .settings_saas import get_saas_settings

settings = get_saas_settings()
_SYMBOL_TO_ID = {
    "btc": "bitcoin",
    "bitcoin": "bitcoin",
    "eth": "ethereum",
    "ethereum": "ethereum",
    "sol": "solana",
    "solana": "solana",
    "xrp": "ripple",
    "ripple": "ripple",
    "ada": "cardano",
    "cardano": "cardano",
    "doge": "dogecoin",
    "dogecoin": "dogecoin",
    "bnb": "binancecoin",
    "ton": "the-open-network",
}
_DEFAULT_OVERVIEW = ["bitcoin", "ethereum", "solana", "ripple", "cardano", "dogecoin"]
_cache: OrderedDict[str, tuple[float, Any]] = OrderedDict()
_cache_lock = asyncio.Lock()


async def _cached(key: str) -> Any | None:
    async with _cache_lock:
        entry = _cache.get(key)
        if not entry:
            return None
        expires_at, value = entry
        if expires_at <= time.time():
            _cache.pop(key, None)
            return None
        _cache.move_to_end(key)
        return value


async def _store(key: str, value: Any) -> None:
    async with _cache_lock:
        _cache[key] = (time.time() + settings.market_cache_ttl_seconds, value)
        _cache.move_to_end(key)
        while len(_cache) > 64:
            _cache.popitem(last=False)


async def _get_json(path: str, *, params: dict[str, Any]) -> Any:
    key = f"{path}?{sorted(params.items())!r}"
    cached = await _cached(key)
    if cached is not None:
        return cached
    headers = {"Accept": "application/json"}
    if settings.coingecko_demo_api_key:
        headers["x-cg-demo-api-key"] = settings.coingecko_demo_api_key
    async with httpx.AsyncClient(timeout=httpx.Timeout(settings.market_timeout_seconds), follow_redirects=False) as client:
        response = await client.get(f"{settings.coingecko_base_url}{path}", params=params, headers=headers)
        response.raise_for_status()
        payload = response.json()
    await _store(key, payload)
    return payload


def detect_asset_ids(text: str) -> list[str]:
    words = {token.lower() for token in re.findall(r"[a-zA-Z]{2,15}", text)}
    ids = [coin_id for token, coin_id in _SYMBOL_TO_ID.items() if token in words]
    ordered = []
    for coin_id in ids:
        if coin_id not in ordered:
            ordered.append(coin_id)
    return ordered[:5]


async def fetch_market_snapshot(asset_ids: list[str]) -> dict[str, Any]:
    if not asset_ids:
        return {}
    payload = await _get_json(
        "/simple/price",
        params={
            "ids": ",".join(asset_ids),
            "vs_currencies": "usd",
            "include_24hr_change": "true",
            "include_24hr_vol": "true",
            "include_market_cap": "true",
            "include_last_updated_at": "true",
        },
    )
    return payload if isinstance(payload, dict) else {}


async def build_market_context(user_text: str) -> str | None:
    asset_ids = detect_asset_ids(user_text)
    if not asset_ids:
        return None
    try:
        snapshot = await fetch_market_snapshot(asset_ids)
    except httpx.HTTPError:
        return None
    lines = ["Recent crypto market snapshot (CoinGecko):"]
    for asset_id in asset_ids:
        row = snapshot.get(asset_id)
        if not isinstance(row, dict):
            continue
        price = row.get("usd")
        change = row.get("usd_24h_change")
        volume = row.get("usd_24h_vol")
        market_cap = row.get("usd_market_cap")
        lines.append(
            f"- {asset_id}: price=${price}, 24h_change={change}, 24h_volume={volume}, market_cap={market_cap}"
        )
    return "\n".join(lines) if len(lines) > 1 else None


async def fetch_market_overview() -> list[dict[str, Any]]:
    payload = await _get_json(
        "/coins/markets",
        params={
            "vs_currency": "usd",
            "ids": ",".join(_DEFAULT_OVERVIEW),
            "order": "market_cap_desc",
            "per_page": str(len(_DEFAULT_OVERVIEW)),
            "page": "1",
            "sparkline": "false",
            "price_change_percentage": "24h",
        },
    )
    result: list[dict[str, Any]] = []
    if not isinstance(payload, list):
        return result
    for item in payload:
        if not isinstance(item, dict):
            continue
        result.append(
            {
                "id": item.get("id"),
                "symbol": str(item.get("symbol", "")).upper(),
                "name": item.get("name"),
                "price": item.get("current_price"),
                "price_change_percentage_24h": item.get("price_change_percentage_24h"),
                "market_cap": item.get("market_cap"),
            }
        )
    return result


def install_market_context_api(app: FastAPI) -> None:
    if getattr(app.state, "market_context_api_installed", False):
        return
    app.state.market_context_api_installed = True

    @app.get("/api/markets/overview")
    async def market_overview() -> JSONResponse:
        try:
            data = await fetch_market_overview()
            return JSONResponse({"status": "ok", "markets": data}, headers={"Cache-Control": "no-store"})
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail={"status": "market_data_unavailable"}) from exc


__all__ = [
    "build_market_context",
    "detect_asset_ids",
    "fetch_market_overview",
    "fetch_market_snapshot",
    "install_market_context_api",
]
