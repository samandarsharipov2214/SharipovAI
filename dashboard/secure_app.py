"""Security-enhanced compatibility entrypoint for SharipovAI.

The production VPS uses ``dashboard:app``. This module remains for tests and
legacy commands, but it now reuses the same lockout implementation instead of
maintaining a second security flow.
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from .app import create_app
from .login_lockout import LoginLockoutMiddleware, install_login_lockout, login_attempt_guard


def create_secure_app(runner_factory: Any | None = None) -> FastAPI:
    dashboard = create_app(runner_factory=runner_factory)
    install_login_lockout(dashboard)
    return dashboard


app = create_secure_app()

__all__ = [
    "LoginLockoutMiddleware",
    "app",
    "create_secure_app",
    "install_login_lockout",
    "login_attempt_guard",
]
