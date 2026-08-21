"""AI Bot Communication Network read-only standalone API and dashboard.

Run with:
    python -m uvicorn learning.bot_communication_app:app --reload

Mutation authority belongs to the canonical dashboard application where authenticated
admin identity, provenance and origin checks are available. The standalone service
remains intentionally read-only so it cannot become a second control plane.
"""

from __future__ import annotations

import os
from html import escape
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from .bot_communication import BotCommunicationNetwork


app = FastAPI(title="SharipovAI Bot Communication Network")


def network() -> BotCommunicationNetwork:
    return BotCommunicationNetwork(Path(os.getenv("BOT_COMMUNICATION_DB", "data/bot_communication.sqlite3")))


def _retired_mutation() -> None:
    raise HTTPException(
        status_code=410,
        detail={
            "status": "standalone_mutations_retired",
            "message": "Use the canonical dashboard Bot Network API for authenticated mutations.",
        },
    )


@app.get("/api/bot-network/health")
def health_api() -> dict[str, Any]:
    health = network().health()
    health["standalone_read_only"] = True
    return health


@app.get("/api/bot-network/matrix")
def matrix_api() -> dict[str, Any]:
    return network().communication_matrix()


@app.post("/api/bot-network/messages")
def send_message_api() -> None:
    _retired_mutation()


@app.post("/api/bot-network/broadcast")
def broadcast_api() -> None:
    _retired_mutation()


@app.post("/api/bot-network/consensus")
def consensus_api() -> None:
    _retired_mutation()


@app.get("/api/bot-network/inbox/{bot_name}")
def inbox_api(bot_name: str, unread_only: bool = False) -> dict[str, Any]:
    return {"status": "ok", "bot": bot_name, "messages": network().inbox(bot_name, unread_only=unread_only)}


@app.get("/api/bot-network/outbox/{bot_name}")
def outbox_api(bot_name: str) -> dict[str, Any]:
    return {"status": "ok", "bot": bot_name, "messages": network().outbox(bot_name)}


@app.get("/api/bot-network/threads/{thread_id}")
def thread_api(thread_id: str) -> dict[str, Any]:
    return network().thread(thread_id)


@app.post("/api/bot-network/messages/{message_id}/read")
def mark_read_api(message_id: str) -> None:
    _retired_mutation()


@app.get("/bot-network", response_class=HTMLResponse)
def bot_network_page() -> HTMLResponse:
    net = network()
    health = net.health()
    rows = "".join(_bot_row(bot, responsibility) for bot, responsibility in health.get("responsibilities", {}).items())
    return HTMLResponse(
        f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>SharipovAI · Bot Network</title><style>{_css()}</style></head><body><main><section class="card"><span class="ok">BOT NETWORK · READ ONLY</span><h1>Связь AI-ботов</h1><p>Standalone-сервис оставлен только для чтения. Управляющие действия выполняются через канонический dashboard API с admin-auth.</p><p><a href="/api/bot-network/health">JSON health</a> · <a href="/api/bot-network/matrix">JSON matrix</a></p></section><section class="card"><div class="grid"><div class="stat"><small>Ботов</small><b>{health.get('bot_count', 0)}</b></div><div class="stat"><small>Messages</small><b>{health.get('message_count', 0)}</b></div><div class="stat"><small>Unread</small><b>{health.get('unread_count', 0)}</b></div><div class="stat"><small>Threads</small><b>{health.get('thread_count', 0)}</b></div><div class="stat"><small>Full mesh</small><b>{'ДА' if health.get('full_mesh_possible') else 'НЕТ'}</b></div></div></section><section class="card"><h2>Боты и роли</h2><table><thead><tr><th>Bot</th><th>Role</th></tr></thead><tbody>{rows}</tbody></table></section></main></body></html>"""
    )


def _bot_row(bot: str, responsibility: str) -> str:
    return f"<tr><td><b>{escape(bot)}</b></td><td>{escape(responsibility)}</td></tr>"


def _css() -> str:
    return "body{margin:0;background:#070b12;color:#eef4ff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}main{padding:18px;max-width:1180px;margin:auto}.card{background:#111827;border:1px solid #243044;border-radius:18px;padding:16px;margin:12px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}.stat{background:#0b1220;border:1px solid #1f2a3d;border-radius:14px;padding:12px}.stat small{display:block;color:#8ea2c4}.stat b{font-size:24px}table{width:100%;border-collapse:collapse}td,th{padding:10px;border-bottom:1px solid #243044;text-align:left;vertical-align:top}.ok{display:inline-block;background:#10b981;color:#03130d;border-radius:999px;padding:6px 10px;font-weight:900}a{color:#60a5fa;font-weight:800}"
