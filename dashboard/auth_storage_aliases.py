"""Unify legacy and canonical authentication storage paths.

Older local tools and tests use ``AUTH_*_FILE`` while the current dashboard uses
``SHARIPOVAI_*_FILE``.  Resolving them in different modules created split-brain
authentication: login could read one users file while the signed-session verifier
read another.  This adapter installs one dynamic resolver for both code paths.
"""
from __future__ import annotations

import importlib
import os
from pathlib import Path
from typing import Callable

_INSTALLED = False


def _resolved_path(
    legacy_name: str,
    canonical_name: str,
    default_factory: Callable[[], Path],
) -> Path:
    """Resolve an explicit legacy alias first, then the canonical name."""

    legacy = os.getenv(legacy_name, "").strip()
    if legacy:
        return Path(legacy)
    canonical = os.getenv(canonical_name, "").strip()
    if canonical:
        return Path(canonical)
    return default_factory()


def install_auth_storage_aliases() -> None:
    """Install dynamic shared path resolvers exactly once per Python process."""

    global _INSTALLED
    if _INSTALLED:
        return

    app_module = importlib.import_module("dashboard.app")
    compat_module = importlib.import_module("dashboard.stabilization_compat")

    def users_file() -> Path:
        return _resolved_path(
            "AUTH_USERS_FILE",
            "SHARIPOVAI_USERS_FILE",
            lambda: app_module._data_dir() / "users.json",
        )

    def access_requests_file() -> Path:
        return _resolved_path(
            "AUTH_ACCESS_REQUESTS_FILE",
            "SHARIPOVAI_ACCESS_REQUESTS_FILE",
            lambda: app_module._data_dir() / "access_requests.json",
        )

    def security_events_file() -> Path:
        return _resolved_path(
            "AUTH_SECURITY_EVENTS_FILE",
            "SHARIPOVAI_SECURITY_EVENTS_FILE",
            lambda: app_module._data_dir() / "security_events.jsonl",
        )

    app_module._users_file = users_file
    app_module._access_requests_file = access_requests_file
    app_module._security_events_file = security_events_file

    compat_module._compat_users_file = users_file
    compat_module._compat_requests_file = access_requests_file
    compat_module._compat_events_file = security_events_file

    _INSTALLED = True


__all__ = ["install_auth_storage_aliases"]
