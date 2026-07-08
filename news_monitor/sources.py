"""Default news/social sources for SharipovAI.

Telegram and X are represented as monitored source definitions first. Direct
reading requires explicit API/session setup and legal access to each source.
"""

from __future__ import annotations

from .models import NewsSource


def default_sources() -> list[NewsSource]:
    """Return curated default sources to monitor.

    This is a broad allowlist, not literally every website on the internet. It
    covers major crypto, finance, macro, exchange, security, and RSS sources.
    """

    return [
        NewsSource("bybit_announcements", "Bybit Announcements", "official", "https://announcements.bybit.com", 92, "exchange", note="Official exchange announcements."),
        NewsSource("binance_announcements", "Binance Announcements", "official", "https://www.binance.com/en/support/announcement", 92, "exchange", note="Official exchange announcements."),
        NewsSource("coinbase_blog", "Coinbase Blog", "rss", "https://www.coinbase.com/blog/rss.xml", 88, "exchange"),
        NewsSource("kraken_blog", "Kraken Blog", "rss", "https://blog.kraken.com/feed", 86, "exchange"),
        NewsSource("cointelegraph_rss", "Cointelegraph", "rss", "https://cointelegraph.com/rss", 75, "crypto_news"),
        NewsSource("coindesk_rss", "CoinDesk", "rss", "https://www.coindesk.com/arc/outboundfeeds/rss/", 78, "crypto_news"),
        NewsSource("decrypt_rss", "Decrypt", "rss", "https://decrypt.co/feed", 70, "crypto_news"),
        NewsSource("theblock_rss", "The Block", "rss", "https://www.theblock.co/rss.xml", 76, "crypto_news"),
        NewsSource("bitcoinmagazine_rss", "Bitcoin Magazine", "rss", "https://bitcoinmagazine.com/.rss/full/", 66, "crypto_news"),
        NewsSource("cryptoslate_rss", "CryptoSlate", "rss", "https://cryptoslate.com/feed/", 64, "crypto_news"),
        NewsSource("newsbtc_rss", "NewsBTC", "rss", "https://www.newsbtc.com/feed/", 58, "crypto_news", note="Use with confirmation."),
        NewsSource("beincrypto_rss", "BeInCrypto", "rss", "https://beincrypto.com/feed/", 60, "crypto_news", note="Use with confirmation."),
        NewsSource("reuters_markets", "Reuters Markets", "rss", "https://www.reutersagency.com/feed/?best-topics=markets&post_type=best", 88, "macro"),
        NewsSource("cnbc_finance", "CNBC Finance", "rss", "https://www.cnbc.com/id/100003114/device/rss/rss.html", 74, "macro"),
        NewsSource("marketwatch_top", "MarketWatch Top Stories", "rss", "https://feeds.content.dowjones.io/public/rss/mw_topstories", 72, "macro"),
        NewsSource("investing_news", "Investing.com News", "rss", "https://www.investing.com/rss/news.rss", 62, "macro", note="Use with confirmation."),
        NewsSource("federal_reserve", "Federal Reserve Press Releases", "rss", "https://www.federalreserve.gov/feeds/press_all.xml", 94, "macro_official"),
        NewsSource("sec_press", "SEC Press Releases", "rss", "https://www.sec.gov/news/pressreleases.rss", 94, "regulation_official"),
        NewsSource("cisa_alerts", "CISA Alerts", "rss", "https://www.cisa.gov/cybersecurity-advisories/all.xml", 90, "security"),
        NewsSource("github_security", "GitHub Security Advisories", "rss", "https://github.com/advisories?query=type%3Areviewed", 80, "security"),
        NewsSource("whale_alert_x", "Whale Alert", "x", "https://x.com/whale_alert", 72, "social", requires_credentials=True, note="Needs X API for direct monitoring."),
        NewsSource("watcher_guru_x", "Watcher.Guru", "x", "https://x.com/WatcherGuru", 58, "social", requires_credentials=True, note="Treat as fast signal; verify before trading."),
        NewsSource("bybit_x", "Bybit X", "x", "https://x.com/Bybit_Official", 82, "social", requires_credentials=True, note="Needs X API for direct monitoring."),
        NewsSource("telegram_bybit", "Telegram: Bybit", "telegram", "@BybitEnglish", 78, "telegram", requires_credentials=True, note="Bot/client must have access to the channel."),
        NewsSource("telegram_cointelegraph", "Telegram: Cointelegraph", "telegram", "@cointelegraph", 70, "telegram", requires_credentials=True, note="Bot/client must have access to the channel."),
        NewsSource("telegram_whale_alert", "Telegram: Whale Alert", "telegram", "@whale_alert_io", 70, "telegram", requires_credentials=True, note="Bot/client must have access to the channel."),
        NewsSource("reddit_crypto", "Reddit CryptoCurrency", "reddit", "https://www.reddit.com/r/CryptoCurrency/", 45, "social", requires_credentials=True, note="High noise; require confirmation."),
        NewsSource("youtube_bybit", "YouTube: Bybit", "youtube", "https://www.youtube.com/@Bybit", 65, "video", requires_credentials=True),
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
