"""Stable routes for SharipovAI dashboard and Mini App."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

import config.settings as config_settings
from ai_chat_orchestrator import answer_chat
from learning_engine import LearningSummary
from runner import SharipovAIRunner
from sharipovai_constitution import apply_agent_discipline, constitution_snapshot, now_iso, paper_realism_state

from .i18n.loader import load_translations, normalize_language
from .models import DashboardView

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
DAILY_GROWTH_TARGET_PERCENT = 1.0
STARTED_MONOTONIC = time.monotonic()
STARTED_AT = now_iso()
WEB2_INDEX = Path(__file__).resolve().parents[1] / "web2" / "out" / "index.html"


def _render(request: Request, page: str):
    if WEB2_INDEX.exists():
        return FileResponse(WEB2_INDEX, media_type="text/html")
    lang = normalize_language(request.query_params.get("lang"))
    t = load_translations(lang)
    view = _safe_view(request)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "page": page,
            "view": view,
            "display": _display(view, t),
            "crash": _stress({}),
            "stress": _stress({}),
            "stress_scenarios": _stress_scenarios(),
            "improvements": _improvements(),
            "settings": config_settings.settings,
            "nav_items": _nav(lang),
            "lang": lang,
            "t": t,
        },
    )


@router.get("/", response_class=HTMLResponse)
def home(request: Request):
    return _render(request, "overview")


@router.get("/market", response_class=HTMLResponse)
def market(request: Request):
    return _render(request, "market")


@router.get("/news", response_class=HTMLResponse)
def news(request: Request):
    return _render(request, "news")


@router.get("/ai-decision", response_class=HTMLResponse)
def ai_decision(request: Request):
    return _render(request, "ai-decision")


@router.get("/portfolio", response_class=HTMLResponse)
def portfolio(request: Request):
    return _render(request, "portfolio")


@router.get("/paper-trading", response_class=HTMLResponse)
def paper_trading(request: Request):
    return _render(request, "paper-trading")


@router.get("/learning", response_class=HTMLResponse)
def learning(request: Request):
    return _render(request, "learning")


@router.get("/self-analysis", response_class=HTMLResponse)
def self_analysis(request: Request):
    return _render(request, "self-analysis")


@router.get("/stress-lab", response_class=HTMLResponse)
def stress_lab(request: Request):
    return _render(request, "stress-lab")


@router.get("/ai-improvement", response_class=HTMLResponse)
def ai_improvement(request: Request):
    return _render(request, "ai-improvement")


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    return _render(request, "settings")


@router.get("/ai-bots", response_class=HTMLResponse)
def ai_bots_page(request: Request):
    return _render(request, "ai-bots")


@router.get("/general-control", response_class=HTMLResponse)
def general_control_page(request: Request):
    return _render(request, "general-control")


@router.get("/learning-os", response_class=HTMLResponse)
def learning_os_page(request: Request):
    return _render(request, "learning-os")


@router.get("/evidence-vault", response_class=HTMLResponse)
def evidence_vault_page(request: Request):
    return _render(request, "evidence-vault")


@router.get("/virtual-account", response_class=HTMLResponse)
def virtual_account_page(request: Request):
    return _render(request, "virtual-account")


@router.get("/control", response_class=HTMLResponse)
def control_page(request: Request):
    return _render(request, "control")


# The remainder of this module contains the existing JSON/API helper routes and
# business logic. It is intentionally imported below to keep the public UI shell
# replaceable without changing those contracts.
