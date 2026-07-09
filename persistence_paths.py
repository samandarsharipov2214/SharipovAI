"""Durable storage path helpers for Render and local SharipovAI state."""

from __future__ import annotations

import os
from pathlib import Path


def durable_data_path(env_name: str, default_relative: str) -> Path:
    """Return a state path that survives Render sleep/redeploy when configured.

    Explicit file env wins. Otherwise Render persistent disk envs can point to a
    durable directory (for example /var/data). Local development keeps the repo
    data/ defaults so existing tests and workflows remain unchanged.
    """

    explicit = os.getenv(env_name)
    if explicit:
        return Path(explicit)
    base = os.getenv("SHARIPOVAI_DATA_DIR") or os.getenv("RENDER_DISK_PATH")
    if base:
        return Path(base) / Path(default_relative).name
    return Path(default_relative)
