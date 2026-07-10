"""Bridge specialized News AI events into the durable bot message bus."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from learning.bot_communication import BotCommunicationNetwork

from .agent_network import network_status

STATE_PATH = Path(os.getenv("NEWS_AGENT_BRIDGE_STATE_FILE", "data/news_agent_bridge.json"))
_THREAD: threading.Thread | None = None
_STOP = threading.Event()
_LOCK = threading.Lock()

ROUTE_MAP = {
    "risk_engine": "risk_engine",
    "trading_ai": "market_agent",
    "portfolio_engine": "portfolio_engine",
    "learning_engine": "learning_engine",
    "security_cyber_ai": "security_guard",
    "world_coordinator": "general_controller",
    "politics_ai": "general_controller",
    "economy_ai": "general_controller",
    "finance_ai": "general_controller",
    "crypto_ai": "market_agent",
    "security_ai": "security_guard",
}


def start_agent_bridge() -> dict[str, Any]:
    global _THREAD
    if os.getenv("NEWS_AGENT_BRIDGE_ENABLED", "1").strip().lower() in {"0", "false", "no", "off"}:
        return {"status": "disabled", "thread_alive": False}
    if _THREAD and _THREAD.is_alive():
        return {"status": "already_running", "thread_alive": True}
    _STOP.clear()
    _THREAD = threading.Thread(target=_loop, name="news-agent-bridge", daemon=True)
    _THREAD.start()
    return {"status": "started", "thread_alive": True}


def bridge_status() -> dict[str, Any]:
    state = _load_state()
    return {"status": "ok", "thread_alive": bool(_THREAD and _THREAD.is_alive()), **state}


def bridge_events() -> dict[str, Any]:
    """Send unseen specialized events to the existing durable message bus."""

    with _LOCK:
        state = _load_state()
        seen = set(state.get("seen_event_ids", []))
        payload = network_status(run_due=False)
        events = [event for event in payload.get("events", []) if event.get("event_id") not in seen]
        network = BotCommunicationNetwork()
        sent = 0
        failures: list[dict[str, Any]] = []
        for event in events:
            recipients = sorted({ROUTE_MAP.get(route, "general_controller") for route in event.get("routes_to", [])})
            recipients = [recipient for recipient in recipients if recipient != "news_agent"]
            message_type = "risk_alert" if event.get("action") == "BLOCK_AND_VERIFY" else "status_update"
            priority = "critical" if event.get("action") == "BLOCK_AND_VERIFY" else "high" if abs(float(event.get("impact_score", 0) or 0)) >= 60 else "normal"
            for recipient in recipients:
                result = network.send_message(
                    sender="news_agent",
                    recipient=recipient,
                    message_type=message_type,
                    topic=f"news_event:{event.get('agent_id')}",
                    payload=event,
                    priority=priority,
                )
                if result.get("status") == "ok":
                    sent += 1
                else:
                    failures.append({"event_id": event.get("event_id"), "recipient": recipient, "result": result})
            seen.add(str(event.get("event_id")))
        state.update(
            {
                "seen_event_ids": list(seen)[-5000:],
                "last_bridge_at": int(time.time()),
                "last_event_count": len(events),
                "last_sent_count": sent,
                "last_failures": failures[-50:],
            }
        )
        _save_state(state)
        return {"status": "ok", "events": len(events), "sent": sent, "failures": failures}


def _loop() -> None:
    while not _STOP.is_set():
        try:
            bridge_events()
        except Exception as exc:  # pragma: no cover
            state = _load_state()
            state["last_error"] = f"{type(exc).__name__}: {exc}"
            state["last_error_at"] = int(time.time())
            _save_state(state)
        _STOP.wait(10)


def _load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {"seen_event_ids": [], "last_bridge_at": 0, "last_sent_count": 0, "last_failures": []}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"seen_event_ids": []}
    except Exception:
        return {"seen_event_ids": []}


def _save_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
