"""Default news/social sources for SharipovAI.

Telegram and X are represented as monitored source definitions first. Direct
reading requires explicit API/session setup and legal access to each source.
"""

from __future__ import annotations

from .models import NewsSource


def default_sources() -> list[NewsSource]:
    """Return curated default sources to monitor."""

    return [
        NewsSource("bybit_announcements", "Bybit Announcements", "official", "https://announcements.bybit.com", 92, "exchange", note="Official exchange announcements."),
        NewsSource("binance_announcements", "Binance Announcements", "official", "https://www.binance.com/en/support/announcement", 92, "exchange", note="Official exchange announcements."),
        NewsSource("cointelegraph_rss", "Cointelegraph", "rss", "https://cointelegraph.com/rss", 75, "news"),
        NewsSource("coindesk_rss", "CoinDesk", "rss", "https://www.coindesk.com/arc/outboundfeeds/rss/", 78, "news"),
        NewsSource("decrypt_rss", "Decrypt", "rss", "https://decrypt.co/feed", 70, "news"),
        NewsSource("whale_alert_x", "Whale Alert", "x", "https://x.com/whale_alert", 72, "social", requires_credentials=True, note="Needs X API for direct monitoring."),
        NewsSource("watcher_guru_x", "Watcher.Guru", "x", "https://x.com/WatcherGuru", 58, "social", requires_credentials=True, note="Treat as fast signal; verify before trading."),
        NewsSource("bybit_x", "Bybit X", "x", "https://x.com/Bybit_Official", 82, "social", requires_credentials=True, note="Needs X API for direct monitoring."),
        NewsSource("telegram_bybit", "Telegram: Bybit", "telegram", "@BybitEnglish", 78, "telegram", requires_credentials=True, note="Bot/client must have access to the channel."),
        NewsSource("telegram_cointelegraph", "Telegram: Cointelegraph", "telegram", "@cointelegraph", 70, "telegram", requires_credentials=True, note="Bot/client must have access to the channel."),
        NewsSource("telegram_whale_alert", "Telegram: Whale Alert", "telegram", "@whale_alert_io", 70, "telegram", requires_credentials=True, note="Bot/client must have access to the channel."),
        NewsSource("reddit_crypto", "Reddit CryptoCurrency", "reddit", "https://www.reddit.com/r/CryptoCurrency/", 45, "social", requires_credentials=True, note="High noise; require confirmation."),
        NewsSource("youtube_bybit", "YouTube: Bybit", "youtube", "https://www.youtube.com/@Bybit", 65, "video", requires_credentials=True),
        NewsSource("github_security", "GitHub Security Advisories", "rss", "https://github.com/advisories?query=type%3Areviewed", 80, "security"),
    ]


def sources_payload() -> dict[str, object]:
    """Return sources grouped for API display."""

    sources = default_sources()
    grouped: dict[str, list[dict[str, object]]] = {}
    for source in sources:
        grouped.setdefault(source.kind, []).append(source.to_dict())
    return {
        "total": len(sources),
        "enabled": sum(1 for source in sources if source.enabled),
        "requires_credentials": sum(1 for source in sources if source.requires_credentials),
        "sources": [source.to_dict() for source in sources],
        "grouped": grouped,
    }
