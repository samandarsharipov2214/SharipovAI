"""Trust, urgency, credibility, and market-impact analyzer for monitored news."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Iterable

from .credibility import error_risk, truth_probability, verification_status
from .models import NewsItem, NewsSource
from .sources import default_sources

SYMBOL_KEYWORDS: dict[str, tuple[str, ...]] = {
    "BTC": ("btc", "bitcoin", "биткоин"),
    "ETH": ("eth", "ethereum", "эфир"),
    "SOL": ("sol", "solana"),
    "BNB": ("bnb", "binance"),
    "USDT": ("usdt", "tether"),
    "USDC": ("usdc",),
}

BULLISH_WORDS = ("listing", "listed", "etf approval", "partnership", "adoption", "inflow", "buyback", "burn", "upgrade", "одобр", "листинг", "партнер", "приток")
BEARISH_WORDS = ("hack", "exploit", "lawsuit", "sec", "delisting", "outflow", "ban", "liquidation", "банкрот", "взлом", "делист", "иск", "запрет", "ликвидац")
URGENT_WORDS = ("breaking", "urgent", "alert", "hack", "exploit", "delisting", "maintenance", "halt", "срочно", "взлом", "делист", "останов")


def analyze_items(raw_items: Iterable[dict[str, object]], sources: list[NewsSource] | None = None) -> list[NewsItem]:
    """Analyze raw items and return normalized NewsItem objects."""

    source_map = {source.id: source for source in (sources or default_sources())}
    raw_list = list(raw_items)
    analyzed: list[NewsItem] = []
    titles = [str(item.get("title", "")) for item in raw_list]
    symbol_counts = _symbol_confirmation_counts(titles)

    for raw in raw_list:
        source_id = str(raw.get("source_id", "manual"))
        source = source_map.get(source_id)
        kind = str(raw.get("kind", source.kind if source else "manual"))
        title = str(raw.get("title", "")).strip() or "Untitled news item"
        summary = str(raw.get("summary", ""))
        text = f"{title} {summary}".lower()
        symbols = _extract_symbols(text)
        tags = _extract_tags(text)
        impact, impact_score = _impact(text)
        urgency = "high" if any(word in text for word in URGENT_WORDS) else "medium" if abs(impact_score) >= 40 else "low"
        trust = int(raw.get("trust_score", source.trust_score if source else 45))
        confirmation_count = max([symbol_counts.get(symbol, 1) for symbol in symbols] or [1])
        needs_confirmation = _needs_confirmation(trust, kind, confirmation_count, urgency)
        credibility = truth_probability(
            trust_score=trust,
            kind=kind,
            confirmation_count=confirmation_count,
            urgency=urgency,
            tags=tags,
        )
        status = verification_status(credibility, confirmation_count, needs_confirmation)
        risk = error_risk(credibility)
        action = _ai_action(impact=impact, trust=trust, urgency=urgency, needs_confirmation=needs_confirmation, credibility=credibility)
        reason = _reason(impact, trust, urgency, needs_confirmation, confirmation_count, credibility, status)
        analyzed.append(
            NewsItem(
                source_id=source_id,
                source_name=str(raw.get("source_name", source.name if source else "Manual")),
                kind=kind,
                title=title,
                url=str(raw.get("url", source.url if source else "")),
                published_at=str(raw.get("published_at", _now_iso())),
                summary=summary,
                symbols=symbols,
                tags=tags,
                trust_score=trust,
                credibility_percent=credibility,
                error_risk=risk,
                verification_status=status,
                urgency=urgency,
                impact=impact,
                impact_score=impact_score,
                needs_confirmation=needs_confirmation,
                confirmation_count=confirmation_count,
                ai_action=action,
                reason=reason,
            )
        )
    return sorted(analyzed, key=lambda item: (item.urgency != "high", -item.credibility_percent, -abs(item.impact_score), -item.trust_score))


def demo_items() -> list[dict[str, object]]:
    """Return deterministic sample news for tests/manual previews only.

    This function is never used as implicit live input. Production paths must
    call analyzed_news_payload(raw_items=real_items) or pass an empty list.
    """

    return [
        {"source_id": "bybit_announcements", "title": "Bybit announces BTC market monitoring and fee updates", "summary": "Official exchange update for BTC traders."},
        {"source_id": "cointelegraph_rss", "title": "Bitcoin ETF inflow increases as market volatility cools", "summary": "ETF inflow and lower volatility can support bullish sentiment."},
        {"source_id": "watcher_guru_x", "title": "Breaking: Large BTC liquidation alert reported on social media", "summary": "Fast social signal requiring confirmation."},
        {"source_id": "telegram_whale_alert", "title": "Whale moved 1200 BTC from exchange wallet", "summary": "Telegram signal; AI should verify with another source."},
        {"source_id": "github_security", "title": "Security advisory reviewed for crypto wallet dependency", "summary": "Security risk can affect market confidence."},
    ]


def analyzed_news_payload(raw_items: Iterable[dict[str, object]] | None = None) -> dict[str, object]:
    """Return API-ready analyzed news payload.

    If raw_items is None, this returns an honest empty analysis. It does not
    inject demo/sample news as live data.
    """

    real_input = raw_items is not None
    items = analyze_items(list(raw_items or []))
    high = [item for item in items if item.urgency == "high"]
    blocked = [item for item in items if item.ai_action == "BLOCK_BUY"]
    confirmations_needed = [item for item in items if item.needs_confirmation]
    avg_credibility = round(sum(item.credibility_percent for item in items) / len(items), 1) if items else 0.0
    low_credibility = [item for item in items if item.credibility_percent < 60]
    return {
        "status": "ok",
        "source_mode": "real_input" if real_input else "empty_no_live_input",
        "summary": {
            "total": len(items),
            "high_urgency": len(high),
            "urgent_count": len(high),
            "block_buy": len(blocked),
            "needs_confirmation": len(confirmations_needed),
            "average_credibility_percent": avg_credibility,
            "low_credibility": len(low_credibility),
            "last_updated": _now_iso(),
            "has_live_items": bool(items),
        },
        "items": [item.to_dict() for item in items],
        "alerts": [item.to_dict() for item in high[:5]],
        "rules": [
            "Do not trade from one Telegram/X post without confirmation.",
            "Require at least two independent sources for social-only claims.",
            "Official exchange/security announcements can block risky trades immediately.",
            "Rank sources by trust, confirmations, source type, urgency, and error risk.",
            "Credibility percent is an estimate for decision safety, not a guarantee of absolute truth.",
            "If no live news items are available, report empty/stale instead of showing sample news as live.",
        ],
    }


def _extract_symbols(text: str) -> list[str]:
    symbols = []
    for symbol, keywords in SYMBOL_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            symbols.append(symbol)
    return symbols


def _extract_tags(text: str) -> list[str]:
    tags = []
    for tag, words in {
        "listing": ("listing", "listed", "листинг"),
        "regulation": ("sec", "lawsuit", "ban", "регуля", "иск"),
        "security": ("hack", "exploit", "security", "взлом"),
        "liquidation": ("liquidation", "ликвидац"),
        "whale": ("whale", "кит"),
        "macro": ("fed", "cpi", "inflation", "ставк", "инфляц"),
    }.items():
        if any(word in text for word in words):
            tags.append(tag)
    return tags


def _impact(text: str) -> tuple[str, int]:
    bullish = sum(1 for word in BULLISH_WORDS if word in text)
    bearish = sum(1 for word in BEARISH_WORDS if word in text)
    score = max(min((bullish - bearish) * 30, 100), -100)
    if score > 0:
        return "bullish", score
    if score < 0:
        return "bearish", score
    return "neutral", 0


def _symbol_confirmation_counts(titles: Iterable[str]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for title in titles:
        for symbol in _extract_symbols(title.lower()):
            counter[symbol] += 1
    return dict(counter)


def _needs_confirmation(trust: int, kind: str, confirmation_count: int, urgency: str) -> bool:
    if kind in {"x", "telegram", "reddit", "youtube"} and confirmation_count < 2:
        return True
    if trust < 70:
        return True
    return urgency == "high" and confirmation_count < 2


def _ai_action(*, impact: str, trust: int, urgency: str, needs_confirmation: bool, credibility: int) -> str:
    if credibility < 55 and urgency == "high":
        return "BLOCK_BUY"
    if needs_confirmation and urgency == "high":
        return "BLOCK_BUY"
    if impact == "bearish" and trust >= 60:
        return "WATCH_OR_REDUCE_RISK"
    if impact == "bullish" and trust >= 75 and not needs_confirmation and credibility >= 75:
        return "ALLOW_ANALYSIS_ONLY"
    return "WATCH"


def _reason(impact: str, trust: int, urgency: str, needs_confirmation: bool, confirmation_count: int, credibility: int, status: str) -> str:
    if needs_confirmation:
        return f"{status}: credibility={credibility}%, trust={trust}, urgency={urgency}, confirmations={confirmation_count}."
    return f"{status}: impact={impact}, credibility={credibility}%, trust={trust}, confirmations={confirmation_count}."


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()
