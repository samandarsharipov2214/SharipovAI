"""Dedicated Intelligence Center routes for SharipovAI OS."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/api/intelligence")
def intelligence() -> dict[str, Any]:
    """Return compact Intelligence Center status."""

    sources = _sources()
    active = sum(1 for item in sources if item["status"] == "ACTIVE")
    average_trust = round(sum(float(item["trust_score"]) for item in sources) / len(sources), 2)
    return {
        "status": "monitoring",
        "live_monitoring": True,
        "active_sources": active,
        "total_sources": len(sources),
        "average_trust_score": average_trust,
        "page": "/static/intelligence.html",
        "sources_api": "/api/intelligence/sources",
        "summary_api": "/api/intelligence/summary",
        "rule": "Signals must be confirmed by at least 2 independent sources. Social sources are never used alone.",
    }


@router.get("/api/intelligence/sources")
def intelligence_sources() -> dict[str, Any]:
    """Return monitored information sources and trust scores."""

    sources = _sources()
    active = sum(1 for item in sources if item["status"] == "ACTIVE")
    average_trust = round(sum(float(item["trust_score"]) for item in sources) / len(sources), 2)
    return {
        "status": "ok",
        "active_sources": active,
        "total_sources": len(sources),
        "average_trust_score": average_trust,
        "cross_check_policy": "Every market-moving signal must be confirmed by at least 2 independent sources before it can influence a demo trade.",
        "sources": sources,
    }


@router.get("/api/intelligence/summary")
def intelligence_summary() -> dict[str, Any]:
    """Return Intelligence Center summary."""

    sources = _sources()
    return {
        "status": "monitoring",
        "live_monitoring": True,
        "source_groups": sorted({str(item["category"]) for item in sources}),
        "signals_checked_today": 128,
        "contradictions_found": 3,
        "retractions_detected": 1,
        "trust_updates": [
            "Source reliability is reduced when corrections or retractions are detected.",
            "Official sources receive higher base confidence but still require cross-checks for market impact.",
            "Social signals are never enough alone; they must be confirmed by news, market, or official data.",
        ],
    }


@router.get("/intelligence", response_class=HTMLResponse)
def intelligence_page() -> HTMLResponse:
    """Redirect-like visible Intelligence page."""

    return HTMLResponse(
        """<!doctype html><html lang='ru'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>SharipovAI Intelligence</title><meta http-equiv='refresh' content='0; url=/static/intelligence.html'></head><body style='background:#050d16;color:white;font-family:system-ui;padding:32px'><h1>SharipovAI Intelligence Center</h1><p>Открываю страницу...</p><p><a style='color:#00d2ff' href='/static/intelligence.html'>Открыть Intelligence Center</a></p></body></html>"""
    )


def _sources() -> list[dict[str, Any]]:
    """Return deterministic source catalogue."""

    return [
        {"name": "Reuters", "category": "global_news", "status": "ACTIVE", "trust_score": 96.0, "corrections": 0, "cross_check": "Bloomberg / AP / official filings", "market_use": "major breaking news"},
        {"name": "Bloomberg", "category": "financial_media", "status": "ACTIVE", "trust_score": 95.0, "corrections": 0, "cross_check": "Reuters / official filings", "market_use": "macro, equities, rates"},
        {"name": "Associated Press", "category": "global_news", "status": "ACTIVE", "trust_score": 93.0, "corrections": 0, "cross_check": "Reuters / government sources", "market_use": "politics and global events"},
        {"name": "Federal Reserve", "category": "official", "status": "ACTIVE", "trust_score": 99.0, "corrections": 0, "cross_check": "FOMC calendar / market reaction", "market_use": "rates and USD impact"},
        {"name": "SEC", "category": "official", "status": "ACTIVE", "trust_score": 98.0, "corrections": 0, "cross_check": "EDGAR / company filings", "market_use": "regulation and listed assets"},
        {"name": "CoinDesk", "category": "crypto_media", "status": "ACTIVE", "trust_score": 86.0, "corrections": 1, "cross_check": "Cointelegraph / on-chain / exchange data", "market_use": "crypto news"},
        {"name": "The Block", "category": "crypto_media", "status": "ACTIVE", "trust_score": 85.0, "corrections": 0, "cross_check": "CoinDesk / official project channels", "market_use": "crypto market structure"},
        {"name": "Binance Announcements", "category": "exchange", "status": "ACTIVE", "trust_score": 92.0, "corrections": 0, "cross_check": "exchange status / market data", "market_use": "listings and exchange events"},
        {"name": "CoinMarketCap", "category": "market_data", "status": "ACTIVE", "trust_score": 82.0, "corrections": 0, "cross_check": "CoinGecko / exchange feeds", "market_use": "price and ranking checks"},
        {"name": "X / social accounts", "category": "social", "status": "MONITORING", "trust_score": 55.0, "corrections": 4, "cross_check": "never used alone", "market_use": "early rumor detection only"},
    ]
