"""Bridge specialized News AI events into the durable bot message bus."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from learning.bot_communication import BotCommunicationNetwork
from persistence_paths import durable_data_path

from .agent_network import network_status

STATE_PATH = durable_data_path("NEWS_AGENT_BRIDGE_STATE_FILE", "data/news_agent_bridge.json")
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
    # Deliver already-created bootstrap events before the background loop starts.
    bootstrap = bridge_events()
    if _THREAD and _THREAD.is_alive():
        return {"status": "already_running", "thread_alive": True, "bootstrap": bootstrap}
    _STOP.clear()
    _THREAD = threading.Thread(target=_loop, name="news-agent-bridge", daemon=True)
    _THREAD.start()
    return {"status": "started", "thread_alive": True, "bootstrap": bootstrap}


def bridge_status() -> dict[str, Any]:
    state = _load_state()
    return {"status": "ok", "thread_alive": bool(_THREAD and _THREAD.is_alive()), **state}


def bridge_events() -> dict[str, Any]:
    """Deliver unseen recipients and retry only failed/missing deliveries."""

    with _LOCK:
        state = _load_state()
        delivered_raw = state.get("delivered", {})
        delivered: dict[str, set[str]] = {
            str(event_id): {str(recipient) for recipient in recipients}
            for event_id, recipients in delivered_raw.items()
            if isinstance(recipients, list)
        } if isinstance(delivered_raw, dict) else {}
        payload = network_status(run_due=False)
        events = [event for event in payload.get("events", []) if isinstance(event, dict) and event.get("event_id")]
        network = BotCommunicationNetwork()
        sent = 0
        attempted = 0
        completed = 0
        failures: list[dict[str, Any]] = []

        for event in events:
            event_id = str(event.get("event_id"))
            recipients = sorted({ROUTE_MAP.get(str(route), "general_controller") for route in event.get("routes_to", [])})
            recipients = [recipient for recipient in recipients if recipient != "news_agent"]
            already = delivered.setdefault(event_id, set())
            missing = [recipient for recipient in recipients if recipient not in already]
            message_type = "risk_alert" if event.get("action") == "BLOCK_AND_VERIFY" else "status_update"
            priority = "critical" if event.get("action") == "BLOCK_AND_VERIFY" else "high" if abs(float(event.get("impact_score", 0) or 0)) >= 60 else "normal"

            for recipient in missing:
                attempted += 1
                result = network.send_message(
                    sender="news_agent",
                    recipient=recipient,
                    message_type=message_type,
                    topic=f"news_event:{event.get('agent_id')}",
                    payload=event,
                    priority=priority,
                )
                if result.get("status") == "ok":
                    already.add(recipient)
                    sent += 1
                else:
                    failures.append({"event_id": event_id, "recipient": recipient, "result": result})
            if recipients and all(recipient in already for recipient in recipients):
                completed += 1

        # Bound state size while preserving the most recent network event order.
        event_order = [str(event.get("event_id")) for event in events][-5000:]
        delivered = {event_id: delivered[event_id] for event_id in event_order if event_id in delivered}
        state.update(
            {
                "delivered": {event_id: sorted(recipients) for event_id, recipients in delivered.items()},
                "seen_event_ids": [event_id for event_id, recipients in delivered.items() if recipients],
                "last_bridge_at": int(time.time()),
                "last_event_count": len(events),
                "last_attempted_count": attempted,
                "last_sent_count": sent,
                "last_completed_count": completed,
                "last_failures": failures[-50:],
            }
        )
        _save_state(state)
        return {"status": "ok" if not failures else "warning", "events": len(events), "attempted": attempted, "sent": sent, "completed": completed, "failures": failures}


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


def _default_state() -> dict[str, Any]:
    return {"delivered": {}, "seen_event_ids": [], "last_bridge_at": 0, "last_sent_count": 0, "last_failures": []}


def _load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return _default_state()
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else _default_state()
    except Exception:
        return _default_state()


def _save_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE_PATH.with_suffix(STATE_PATH.suffix + ".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(STATE_PATH)
