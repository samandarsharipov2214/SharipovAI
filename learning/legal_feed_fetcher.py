"""Legal feed fetcher and monitor orchestrator for SharipovAI.

This layer turns official RSS/Atom/search feed entries into legal watcher items,
then sends them through the watcher, General Controller advice, and Learning
Engine material generation.
"""

from __future__ import annotations

import hashlib
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any

from .legal_source_watcher import LegalWatchStateStore, legal_source_registry, watch_with_store
from .material_ingestion import ingest_material


DEFAULT_FEEDS = [
    {
        "id": "SEC-NEWS",
        "region": "us",
        "source_domain": "sec.gov",
        "source_type": "regulator_docs",
        "topic": "securities_law",
        "url": "https://www.sec.gov/news/pressreleases.rss",
    },
    {
        "id": "FINRA-NEWS",
        "region": "us",
        "source_domain": "finra.org",
        "source_type": "regulator_docs",
        "topic": "consumer_protection",
        "url": "https://www.finra.org/media-center/newsreleases/rss.xml",
    },
    {
        "id": "FCA-NEWS",
        "region": "uk",
        "source_domain": "fca.org.uk",
        "source_type": "regulator_docs",
        "topic": "consumer_protection",
        "url": "https://www.fca.org.uk/news/rss.xml",
    },
]


def legal_feed_registry(region: str = "global") -> dict[str, Any]:
    """Return configured RSS/Atom feeds plus static source registry."""

    selected = region.strip().lower() or "global"
    feeds = [feed for feed in DEFAULT_FEEDS if selected == "global" or feed["region"] in {selected, "global"}]
    sources = legal_source_registry(selected).get("sources", [])
    return {"status": "ok", "region": selected, "feeds": feeds, "sources": sources}


def fetch_feed_entries(feed: dict[str, Any], *, timeout: int = 15) -> dict[str, Any]:
    """Fetch one RSS/Atom feed and normalize entries.

    Network errors are returned as data, not raised, so the orchestrator can
    continue with other feeds.
    """

    url = str(feed.get("url", ""))
    if not url.startswith("https://"):
        return {"status": "invalid_feed_url", "feed": feed.get("id"), "url": url, "entries": []}
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "SharipovAI-LegalMonitor/1.0"})
        with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec - controlled official feed URL registry
            xml_text = response.read().decode("utf-8", errors="replace")
    except Exception as exc:
        return {"status": "fetch_error", "feed": feed.get("id"), "url": url, "error": str(exc), "entries": []}
    return {"status": "ok", "feed": feed.get("id"), "url": url, "entries": parse_feed_entries(xml_text, feed)}


def parse_feed_entries(xml_text: str, feed: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse RSS/Atom XML into legal watcher items."""

    root = ET.fromstring(xml_text)
    entries: list[dict[str, Any]] = []
    rss_items = root.findall(".//item")
    atom_items = root.findall(".//{http://www.w3.org/2005/Atom}entry")

    for item in rss_items:
        title = _text(item, "title")
        link = _text(item, "link")
        summary = _strip_html(_text(item, "description"))
        published = _text(item, "pubDate")
        entries.append(_entry_to_legal_item(feed, title, link, summary, published))

    for item in atom_items:
        title = _atom_text(item, "title")
        link = _atom_link(item)
        summary = _strip_html(_atom_text(item, "summary") or _atom_text(item, "content"))
        published = _atom_text(item, "updated") or _atom_text(item, "published")
        entries.append(_entry_to_legal_item(feed, title, link, summary, published))

    return [entry for entry in entries if entry["title"]]


def run_legal_monitor_cycle(
    *,
    feeds: list[dict[str, Any]] | None = None,
    store: LegalWatchStateStore,
    fetched_items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run one legal monitor cycle.

    In production, feeds are fetched. In tests or offline mode, fetched_items can
    be supplied directly.
    """

    fetched_reports: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = list(fetched_items or [])
    for feed in feeds or []:
        report = fetch_feed_entries(feed)
        fetched_reports.append(report)
        items.extend(report.get("entries", []))

    watch = watch_with_store(items, store)
    learning_materials = [_alert_to_learning_material(alert) for alert in watch.get("alerts", []) if alert.get("status") == "ok"]
    return {
        "status": "ok",
        "fetched_reports": fetched_reports,
        "item_count": len(items),
        "watch": watch,
        "learning_materials": learning_materials,
        "controller_advice": watch.get("controller_advice", {}),
    }


def _alert_to_learning_material(alert: dict[str, Any]) -> dict[str, Any]:
    """Convert a legal alert into a Learning Engine safe material."""

    content = " ".join(
        [
            str(alert.get("title", "")),
            str(alert.get("topic", "")),
            str(alert.get("severity", "")),
            str(alert.get("general_controller_advice", {}).get("message", "")),
        ]
    )
    if len(content) < 80:
        content = content + " Legal regulatory update for SharipovAI bots. Review compliance risk and update rules."
    return ingest_material(
        title=f"Legal alert: {alert.get('title', 'Untitled')}",
        source_type="official_document",
        domain="regulation",
        content=content,
        bots=alert.get("affected_bots", ["general_controller", "security_guard", "learning_engine"]),
        rights="official_or_metadata_summary_for_private_learning",
    )


def _entry_to_legal_item(feed: dict[str, Any], title: str, link: str, summary: str, published: str) -> dict[str, Any]:
    return {
        "title": title.strip(),
        "topic": feed.get("topic", "regulation"),
        "source_domain": feed.get("source_domain", ""),
        "source_type": feed.get("source_type", "regulator_docs"),
        "url": link.strip(),
        "published_at": published.strip(),
        "summary": summary.strip() or title.strip(),
        "feed_id": feed.get("id"),
        "entry_id": _entry_id(feed, title, link, published),
    }


def _entry_id(feed: dict[str, Any], title: str, link: str, published: str) -> str:
    raw = f"{feed.get('id')}|{title}|{link}|{published}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _text(item: ET.Element, tag: str) -> str:
    found = item.find(tag)
    return "" if found is None or found.text is None else found.text.strip()


def _atom_text(item: ET.Element, tag: str) -> str:
    found = item.find(f"{{http://www.w3.org/2005/Atom}}{tag}")
    return "" if found is None or found.text is None else found.text.strip()


def _atom_link(item: ET.Element) -> str:
    found = item.find("{http://www.w3.org/2005/Atom}link")
    if found is None:
        return ""
    return str(found.attrib.get("href", ""))


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text).replace("&nbsp;", " ").strip()
