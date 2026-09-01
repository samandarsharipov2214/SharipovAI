"""Production-mounted Site V1 access approval center."""
from __future__ import annotations

from html import escape
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

from .admin_guard import require_admin
from .auth_saas import _access_request_rows
from .db_saas import SessionLocal


def _legacy_access_request_rows() -> list[dict[str, Any]]:
    """Return display-only compatibility requests while legacy Web2 is retained."""
    from . import stabilization_compat as compat

    return [
        {
            "id": str(item.get("id", "")),
            "name": str(item.get("username", "")),
            "email": "",
            "contact": str(item.get("contact", "")),
            "reason": str(item.get("reason", "")),
            "status": str(item.get("status", "pending")),
            "created_at": str(item.get("created_at", "")),
        }
        for item in compat._load_requests()
    ]


def _access_rows() -> list[dict[str, Any]]:
    db = SessionLocal()
    try:
        rows = _access_request_rows(db)
    finally:
        db.close()
    rows.extend(_legacy_access_request_rows())
    return rows


def _security_center_html(*, username: str, requests: list[dict[str, Any]]) -> str:
    pending_count = sum(1 for entry in requests if entry.get("status") == "pending")
    rows = "".join(
        "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            escape(str(entry.get("name", ""))),
            escape(str(entry.get("email", ""))),
            escape(str(entry.get("contact", ""))),
            escape(str(entry.get("reason", ""))),
            escape(str(entry.get("created_at", ""))),
            escape(str(entry.get("status", ""))),
            (
                "<form method='post' action='/api/security/access-requests/{}/approve'><button>Approve</button></form>"
                "<form method='post' action='/api/security/access-requests/{}/reject'><button>Reject</button></form>"
            ).format(
                escape(str(entry.get("id", ""))),
                escape(str(entry.get("id", ""))),
            )
            if entry.get("status") == "pending"
            else "—",
        )
        for entry in requests
    ) or "<tr><td colspan='7'>Нет данных</td></tr>"
    return f"""<!doctype html><html lang='ru'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>SharipovAI · Кибер-безопасность</title><style>body{{min-height:100vh;margin:0;background:#020817;color:#f8fbff;font-family:Inter,system-ui,sans-serif}}main{{width:min(1200px,94vw);margin:40px auto}}.card{{border:1px solid #38bdf844;background:#071426;border-radius:28px;padding:24px;box-shadow:0 30px 80px #0008}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px}}.stat{{border:1px solid #ffffff18;border-radius:18px;padding:16px;background:#0b1b2c}}small{{color:#94a3b8}}table{{width:100%;border-collapse:collapse;margin-top:20px}}td,th{{padding:10px;border-bottom:1px solid #ffffff18;text-align:left;vertical-align:top}}form{{display:inline}}button{{margin:2px;padding:7px 10px}}.table{{overflow:auto}}</style></head><body><main><h1>Кибер-безопасность</h1><p>Администратор: {escape(username)}</p><section class='card'><div class='grid'><div class='stat'><small>Статус</small><h2>Защищено</h2></div><div class='stat'><small>Заявки</small><h2>{pending_count}</h2></div><div class='stat'><small>Роль</small><h2>admin</h2></div></div><div class='table'><table><thead><tr><th>Имя</th><th>Email</th><th>Контакт</th><th>Причина</th><th>Создано</th><th>Статус</th><th>Решение</th></tr></thead><tbody>{rows}</tbody></table></div></section></main></body></html>"""


def install_site_v1_admin(app: FastAPI) -> None:
    """Mount the canonical approval queue on the actual production app graph."""
    if getattr(app.state, "site_v1_admin_installed", False):
        return
    app.state.site_v1_admin_installed = True

    @app.get("/security", response_class=HTMLResponse)
    def security_center(request: Request) -> HTMLResponse:
        username = require_admin(request)
        return HTMLResponse(
            _security_center_html(username=username, requests=_access_rows()),
            headers={"Cache-Control": "no-store"},
        )


__all__ = ["install_site_v1_admin"]
