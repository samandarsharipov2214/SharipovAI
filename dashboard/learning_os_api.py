"""Dashboard integration for unified SharipovAI Learning OS."""

from __future__ import annotations

import os
from html import escape
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI
from fastapi.responses import HTMLResponse

from learning.learning_memory import LearningMemory
from learning.learning_os_core import bot_training_status, close_learning_gap, learning_os_snapshot


def install_learning_os_api(app: FastAPI) -> None:
    """Install Learning OS dashboard endpoints once."""

    if getattr(app.state, "learning_os_api_installed", False):
        return
    app.state.learning_os_api_installed = True

    def memory() -> LearningMemory:
        return LearningMemory(Path(os.getenv("LEARNING_MEMORY_DB", "data/learning_memory.sqlite3")))

    def snapshot() -> dict[str, Any]:
        return learning_os_snapshot(memory())

    @app.get("/api/learning-os/snapshot")
    def learning_os_snapshot_api() -> dict[str, Any]:
        return snapshot()

    @app.get("/api/learning-os/status")
    def learning_os_status_api() -> dict[str, Any]:
        """Return the compact, UI-stable Learning OS contract.

        This is an alias over the canonical snapshot, not a synthetic fallback.
        The normalized ``items`` collection lets every dashboard version consume
        the same persistent learning memory without guessing nested keys.
        """

        snap = snapshot()
        memory_snapshot = snap.get("memory", {}) if isinstance(snap.get("memory"), dict) else {}
        lessons = memory_snapshot.get("recent_lessons", [])
        if not isinstance(lessons, list):
            lessons = []
        summary = snap.get("summary", {}) if isinstance(snap.get("summary"), dict) else {}
        return {
            "status": "ok",
            "system": snap.get("system", "SharipovAI Learning OS"),
            "mode": snap.get("mode", "controlled_self_learning"),
            "source": "learning_memory",
            "summary": summary,
            "count": len(lessons),
            "items": lessons,
            "lessons": lessons,
            "bots": snap.get("bots", []),
            "memory": memory_snapshot,
            "snapshot": snap,
        }

    @app.post("/api/learning-os/close-gap")
    def close_gap_api() -> dict[str, Any]:
        return close_learning_gap(memory())

    @app.get("/api/learning-os/bots/{bot_name}")
    def bot_status_api(bot_name: str) -> dict[str, Any]:
        return bot_training_status(bot_name, memory=memory())

    @app.post("/api/learning-os/mistakes")
    def record_mistake_api(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
        data = payload or {}
        return memory().record_mistake(
            bot=str(data.get("bot", "learning_engine")),
            domain=str(data.get("domain", "general")),
            mistake=str(data.get("mistake", "unknown mistake")),
            consequence=str(data.get("consequence", "unknown consequence")),
            source=str(data.get("source", "dashboard_api")),
        )

    @app.get("/learning-os", response_class=HTMLResponse)
    def learning_os_page() -> HTMLResponse:
        return HTMLResponse(_render_learning_os(snapshot()))


def _render_learning_os(snap: dict[str, Any]) -> str:
    summary = snap.get("summary", {})
    rows = "".join(_bot_row(bot) for bot in snap.get("bots", []))
    lessons = "".join(_lesson_row(item) for item in snap.get("memory", {}).get("recent_lessons", [])) or "<tr><td colspan='4'>Пока нет уроков.</td></tr>"
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>SharipovAI · Learning OS</title><style>{_css()}</style></head><body><main><section class="card"><span class="ok">LEARNING OS</span><h1>Самообучение SharipovAI</h1><p>Финальный центр обучения: память, источники, юридический мониторинг, экзамены и training status всех ботов.</p><p><a href="/">Главная</a> · <a href="/api/learning-os/snapshot">JSON snapshot</a></p></section><section class="card"><h2>Закрытие раздела</h2><div class="grid"><div class="stat"><small>Ботов</small><b>{summary.get('bot_count', 0)}</b></div><div class="stat"><small>Ready</small><b>{summary.get('ready', 0)}</b></div><div class="stat"><small>Needs training</small><b>{summary.get('needs_training', 0)}</b></div><div class="stat"><small>Learning gap closed</small><b>{'ДА' if summary.get('learning_gap_closed') else 'НЕТ'}</b></div><div class="stat"><small>Уроков</small><b>{summary.get('lesson_count', 0)}</b></div><div class="stat"><small>Экзаменов</small><b>{summary.get('exam_count', 0)}</b></div></div></section><section class="card"><h2>Боты</h2><table><thead><tr><th>Bot</th><th>Status</th><th>Score</th><th>Domains</th><th>Lessons</th></tr></thead><tbody>{rows}</tbody></table></section><section class="card"><h2>Последние уроки</h2><table><thead><tr><th>Bot</th><th>Domain</th><th>Lesson</th><th>Rule</th></tr></thead><tbody>{lessons}</tbody></table></section></main></body></html>"""


def _bot_row(bot: dict[str, Any]) -> str:
    status = str(bot.get("status", "unknown"))
    css = "ok" if status == "ready" else "bad"
    domains = ", ".join(str(item) for item in bot.get("domains", []))
    return f"<tr><td><b>{escape(str(bot.get('bot', 'bot')))}</b></td><td><span class='{css}'>{escape(status)}</span></td><td>{escape(str(bot.get('score', 0)))}</td><td>{escape(domains)}</td><td>{escape(str(bot.get('lesson_count', 0)))}</td></tr>"


def _lesson_row(item: dict[str, Any]) -> str:
    return f"<tr><td>{escape(str(item.get('bot', '')))}</td><td>{escape(str(item.get('domain', '')))}</td><td>{escape(str(item.get('lesson', '')))}</td><td>{escape(str(item.get('rule', '')))}</td></tr>"


def _css() -> str:
    return "body{margin:0;background:#070b12;color:#eef4ff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}main{padding:18px;max-width:1180px;margin:auto}.card{background:#111827;border:1px solid #243044;border-radius:18px;padding:16px;margin:12px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}.stat{background:#0b1220;border:1px solid #1f2a3d;border-radius:14px;padding:12px}.stat small{display:block;color:#8ea2c4}.stat b{font-size:24px}table{width:100%;border-collapse:collapse}td,th{padding:10px;border-bottom:1px solid #243044;text-align:left;vertical-align:top}.ok{display:inline-block;background:#10b981;color:#03130d;border-radius:999px;padding:6px 10px;font-weight:900}.bad{display:inline-block;background:#ef4444;color:#fff;border-radius:999px;padding:6px 10px;font-weight:900}a{color:#60a5fa;font-weight:800}"
