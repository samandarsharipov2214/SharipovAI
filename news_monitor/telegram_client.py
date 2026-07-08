"""Safe Telegram user-client reader for Social News Monitor.

This module is intentionally read-only. It never sends messages, never joins
channels automatically, and reads only allowlisted public/channel usernames from
environment configuration.

Required env vars for real reading:
- TELEGRAM_API_ID
- TELEGRAM_API_HASH
- TELEGRAM_SESSION_STRING
- TELEGRAM_NEWS_SOURCES=@channel1,@channel2

To create TELEGRAM_SESSION_STRING, run scripts/create_telegram_session.py locally
or in a temporary trusted environment, then store the value only in Render env.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from typing import Any

try:  # pragma: no cover - import availability is environment-dependent
    from telethon import TelegramClient
    from telethon.sessions import StringSession
except Exception:  # pragma: no cover
    TelegramClient = None  # type: ignore[assignment]
    StringSession = None  # type: ignore[assignment]


def telegram_client_status() -> dict[str, object]:
    """Return safe Telegram client configuration status without secrets."""

    sources = configured_sources()
    missing = []
    if TelegramClient is None or StringSession is None:
        missing.append("telethon")
    if not os.getenv("TELEGRAM_API_ID"):
        missing.append("TELEGRAM_API_ID")
    if not os.getenv("TELEGRAM_API_HASH"):
        missing.append("TELEGRAM_API_HASH")
    if not os.getenv("TELEGRAM_SESSION_STRING"):
        missing.append("TELEGRAM_SESSION_STRING")
    if not sources:
        missing.append("TELEGRAM_NEWS_SOURCES")
    return {
        "configured": not missing,
        "enabled": os.getenv("TELEGRAM_CLIENT_ENABLED", "0") == "1",
        "read_only": True,
        "auto_join": False,
        "sources": sources,
        "source_count": len(sources),
        "missing": missing,
        "message": "Telegram client готов к чтению allowlist источников." if not missing else "Telegram client ещё не настроен полностью.",
    }


def configured_sources() -> list[str]:
    """Return configured Telegram sources from env."""

    raw = os.getenv("TELEGRAM_NEWS_SOURCES", "")
    return [item.strip() for item in raw.split(",") if item.strip()]


def read_latest_messages(limit_per_source: int = 5) -> dict[str, object]:
    """Synchronously read latest Telegram messages using the async client."""

    status = telegram_client_status()
    if not status["configured"] or not status["enabled"]:
        return {"status": "disabled", "telegram": status, "items": []}
    try:
        items = asyncio.run(_read_latest_messages(limit_per_source=limit_per_source))
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            items = loop.run_until_complete(_read_latest_messages(limit_per_source=limit_per_source))
        finally:
            loop.close()
    except Exception as exc:
        return {"status": "error", "telegram": status, "error": f"{type(exc).__name__}: {exc}", "items": []}
    return {"status": "ok", "telegram": status, "items": items}


async def _read_latest_messages(limit_per_source: int = 5) -> list[dict[str, object]]:
    """Read latest messages from configured Telegram sources."""

    if TelegramClient is None or StringSession is None:
        return []
    api_id = int(os.environ["TELEGRAM_API_ID"])
    api_hash = os.environ["TELEGRAM_API_HASH"]
    session = os.environ["TELEGRAM_SESSION_STRING"]
    sources = configured_sources()
    items: list[dict[str, object]] = []
    async with TelegramClient(StringSession(session), api_id, api_hash) as client:
        for source in sources:
            async for message in client.iter_messages(source, limit=max(int(limit_per_source), 1)):
                text = (message.message or "").strip()
                if not text:
                    continue
                title = text.splitlines()[0][:180]
                items.append(
                    {
                        "source_id": f"telegram_{source.strip('@').lower()}",
                        "source_name": f"Telegram: {source}",
                        "kind": "telegram",
                        "title": title,
                        "summary": text[:700],
                        "url": _message_url(source, getattr(message, "id", None)),
                        "published_at": _date_to_iso(getattr(message, "date", None)),
                        "trust_score": 65,
                    }
                )
    return items


def _message_url(source: str, message_id: Any) -> str:
    username = source.strip().lstrip("@")
    if not username or message_id is None:
        return ""
    return f"https://t.me/{username}/{message_id}"


def _date_to_iso(value: Any) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.isoformat()
    return datetime.now(tz=UTC).isoformat()
