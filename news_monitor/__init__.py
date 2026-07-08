"""Social news monitoring for SharipovAI.

The first layer is safe and read-only: seeded sources, RSS support, trust scoring,
market impact scoring, and API-ready JSON outputs. Direct Telegram/X ingestion
is added later with explicit credentials and source permissions.
"""

from __future__ import annotations

from .analyzer import analyze_items
from .models import NewsItem, NewsSource
from .sources import default_sources
from .storage import load_news_state, save_news_state

__all__ = (
    "NewsItem",
    "NewsSource",
    "analyze_items",
    "default_sources",
    "load_news_state",
    "save_news_state",
)
