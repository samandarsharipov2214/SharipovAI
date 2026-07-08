"""Default news/social sources for SharipovAI.

Telegram and X are represented as monitored source definitions first. Direct
reading requires explicit API/session setup and legal access to each source.
"""

from __future__ import annotations

from .models import NewsSource


def default_sources() -> list[NewsSource]:
    """Return a broad categorized allowlist of sources to monitor."""

    return [
        # Exchange / official crypto
        NewsSource("bybit_announcements", "Bybit Announcements", "official", "https://announcements.bybit.com", 92, "exchange", note="Official exchange announcements."),
        NewsSource("binance_announcements", "Binance Announcements", "official", "https://www.binance.com/en/support/announcement", 92, "exchange", note="Official exchange announcements."),
        NewsSource("coinbase_blog", "Coinbase Blog", "rss", "https://www.coinbase.com/blog/rss.xml", 88, "exchange"),
        NewsSource("kraken_blog", "Kraken Blog", "rss", "https://blog.kraken.com/feed", 86, "exchange"),
        NewsSource("okx_blog", "OKX Blog", "rss", "https://www.okx.com/learn/rss", 78, "exchange"),
        NewsSource("bitget_news", "Bitget News", "rss", "https://www.bitget.com/support/sections/12508313405721/rss", 72, "exchange", note="Use with confirmation."),

        # Crypto / markets
        NewsSource("cointelegraph_rss", "Cointelegraph", "rss", "https://cointelegraph.com/rss", 75, "crypto_news"),
        NewsSource("coindesk_rss", "CoinDesk", "rss", "https://www.coindesk.com/arc/outboundfeeds/rss/", 78, "crypto_news"),
        NewsSource("decrypt_rss", "Decrypt", "rss", "https://decrypt.co/feed", 70, "crypto_news"),
        NewsSource("theblock_rss", "The Block", "rss", "https://www.theblock.co/rss.xml", 76, "crypto_news"),
        NewsSource("bitcoinmagazine_rss", "Bitcoin Magazine", "rss", "https://bitcoinmagazine.com/.rss/full/", 66, "crypto_news"),
        NewsSource("cryptoslate_rss", "CryptoSlate", "rss", "https://cryptoslate.com/feed/", 64, "crypto_news"),
        NewsSource("newsbtc_rss", "NewsBTC", "rss", "https://www.newsbtc.com/feed/", 58, "crypto_news", note="Use with confirmation."),
        NewsSource("beincrypto_rss", "BeInCrypto", "rss", "https://beincrypto.com/feed/", 60, "crypto_news", note="Use with confirmation."),
        NewsSource("ambcrypto_rss", "AMBCrypto", "rss", "https://ambcrypto.com/feed/", 54, "crypto_news", note="Use with confirmation."),
        NewsSource("u_today_rss", "U.Today", "rss", "https://u.today/rss", 55, "crypto_news", note="Use with confirmation."),
        NewsSource("cryptopotato_rss", "CryptoPotato", "rss", "https://cryptopotato.com/feed/", 58, "crypto_news", note="Use with confirmation."),
        NewsSource("bitcoinist_rss", "Bitcoinist", "rss", "https://bitcoinist.com/feed/", 56, "crypto_news", note="Use with confirmation."),

        # World / macro / finance
        NewsSource("reuters_markets", "Reuters Markets", "rss", "https://www.reutersagency.com/feed/?best-topics=markets&post_type=best", 88, "world_finance"),
        NewsSource("cnbc_finance", "CNBC Finance", "rss", "https://www.cnbc.com/id/100003114/device/rss/rss.html", 74, "world_finance"),
        NewsSource("marketwatch_top", "MarketWatch Top Stories", "rss", "https://feeds.content.dowjones.io/public/rss/mw_topstories", 72, "world_finance"),
        NewsSource("investing_news", "Investing.com News", "rss", "https://www.investing.com/rss/news.rss", 62, "world_finance", note="Use with confirmation."),
        NewsSource("ap_top_news", "Associated Press Top News", "rss", "https://feeds.apnews.com/apnews/topnews", 86, "world_news"),
        NewsSource("bbc_world", "BBC World", "rss", "https://feeds.bbci.co.uk/news/world/rss.xml", 82, "world_news"),
        NewsSource("guardian_world", "The Guardian World", "rss", "https://www.theguardian.com/world/rss", 76, "world_news"),
        NewsSource("npr_news", "NPR News", "rss", "https://feeds.npr.org/1001/rss.xml", 78, "world_news"),
        NewsSource("dw_world", "DW World", "rss", "https://rss.dw.com/rdf/rss-en-world", 74, "world_news"),
        NewsSource("aljazeera", "Al Jazeera", "rss", "https://www.aljazeera.com/xml/rss/all.xml", 70, "world_news", note="Use with confirmation on conflicts."),

        # Official macro / regulation
        NewsSource("federal_reserve", "Federal Reserve Press Releases", "rss", "https://www.federalreserve.gov/feeds/press_all.xml", 94, "macro_official"),
        NewsSource("sec_press", "SEC Press Releases", "rss", "https://www.sec.gov/news/pressreleases.rss", 94, "regulation_official"),
        NewsSource("treasury_press", "US Treasury Press Releases", "rss", "https://home.treasury.gov/news/press-releases/rss", 90, "macro_official"),
        NewsSource("ecb_press", "European Central Bank", "rss", "https://www.ecb.europa.eu/rss/press.html", 90, "macro_official"),
        NewsSource("bis_press", "Bank for International Settlements", "rss", "https://www.bis.org/list/press_releases/index.rss", 88, "macro_official"),

        # Security / tech risk
        NewsSource("cisa_alerts", "CISA Alerts", "rss", "https://www.cisa.gov/cybersecurity-advisories/all.xml", 90, "security"),
        NewsSource("github_security", "GitHub Security Advisories", "rss", "https://github.com/advisories?query=type%3Areviewed", 80, "security"),
        NewsSource("hackernews_rss", "Hacker News", "rss", "https://news.ycombinator.com/rss", 62, "tech_security", note="High noise; require confirmation."),
        NewsSource("bleepingcomputer", "BleepingComputer", "rss", "https://www.bleepingcomputer.com/feed/", 74, "security"),
        NewsSource("thehackernews", "The Hacker News", "rss", "https://feeds.feedburner.com/TheHackersNews", 70, "security"),

        # Sports
        NewsSource("espn_top", "ESPN Top News", "rss", "https://www.espn.com/espn/rss/news", 72, "sports"),
        NewsSource("bbc_sport", "BBC Sport", "rss", "https://feeds.bbci.co.uk/sport/rss.xml", 78, "sports"),
        NewsSource("sky_sports", "Sky Sports", "rss", "https://www.skysports.com/rss/12040", 72, "sports"),
        NewsSource("guardian_sport", "The Guardian Sport", "rss", "https://www.theguardian.com/sport/rss", 72, "sports"),
        NewsSource("nfl_news", "NFL News", "rss", "https://www.nfl.com/rss/rsslanding?searchString=home", 70, "sports"),
        NewsSource("nba_news", "NBA News", "rss", "https://www.nba.com/rss/nba_rss.xml", 70, "sports"),

        # Weather / disasters
        NewsSource("noaa_alerts", "NOAA Alerts", "rss", "https://alerts.weather.gov/cap/us.php?x=0", 92, "weather"),
        NewsSource("nhc_atlantic", "National Hurricane Center Atlantic", "rss", "https://www.nhc.noaa.gov/index-at.xml", 92, "weather"),
        NewsSource("gdacs_alerts", "GDACS Alerts", "rss", "https://www.gdacs.org/xml/rss.xml", 82, "weather_disaster"),
        NewsSource("reliefweb_disasters", "ReliefWeb Disasters", "rss", "https://reliefweb.int/disasters/rss.xml", 80, "weather_disaster"),
        NewsSource("earthquake_usgs", "USGS Earthquakes", "rss", "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/significant_month.atom", 92, "weather_disaster"),

        # Social / credentials needed
        NewsSource("whale_alert_x", "Whale Alert", "x", "https://x.com/whale_alert", 72, "x_news", requires_credentials=True, note="Needs X API for direct monitoring."),
        NewsSource("watcher_guru_x", "Watcher.Guru", "x", "https://x.com/WatcherGuru", 58, "x_news", requires_credentials=True, note="Treat as fast signal; verify before trading."),
        NewsSource("bybit_x", "Bybit X", "x", "https://x.com/Bybit_Official", 82, "x_news", requires_credentials=True, note="Needs X API for direct monitoring."),
        NewsSource("telegram_bybit", "Telegram: Bybit", "telegram", "@BybitEnglish", 78, "telegram_news", requires_credentials=True, note="Bot/client must have access to the channel."),
        NewsSource("telegram_cointelegraph", "Telegram: Cointelegraph", "telegram", "@cointelegraph", 70, "telegram_news", requires_credentials=True, note="Bot/client must have access to the channel."),
        NewsSource("telegram_whale_alert", "Telegram: Whale Alert", "telegram", "@whale_alert_io", 70, "telegram_news", requires_credentials=True, note="Bot/client must have access to the channel."),
        NewsSource("reddit_crypto", "Reddit CryptoCurrency", "reddit", "https://www.reddit.com/r/CryptoCurrency/", 45, "social_news", requires_credentials=True, note="High noise; require confirmation."),
        NewsSource("youtube_bybit", "YouTube: Bybit", "youtube", "https://www.youtube.com/@Bybit", 65, "youtube_news", requires_credentials=True),
        NewsSource("youtube_coinbureau", "YouTube: Coin Bureau", "youtube", "https://www.youtube.com/@CoinBureau", 52, "youtube_news", requires_credentials=True, note="Opinion; require confirmation."),
    ]


def sources_payload() -> dict[str, object]:
    """Return sources grouped for API display."""

    sources = default_sources()
    grouped: dict[str, list[dict[str, object]]] = {}
    by_category: dict[str, list[dict[str, object]]] = {}
    for source in sources:
        payload = source.to_dict()
        grouped.setdefault(source.kind, []).append(payload)
        by_category.setdefault(source.category, []).append(payload)
    return {
        "total": len(sources),
        "enabled": sum(1 for source in sources if source.enabled),
        "requires_credentials": sum(1 for source in sources if source.requires_credentials),
        "sources": [source.to_dict() for source in sources],
        "grouped": grouped,
        "by_category": by_category,
    }
