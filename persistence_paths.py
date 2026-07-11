"""Durable storage path helpers for Render and local SharipovAI state."""

from __future__ import annotations

import os
from pathlib import Path


def durable_data_path(env_name: str, default_relative: str) -> Path:
    """Return a durable state path for local Windows, Render, and tests.

    Explicit file env wins. Otherwise Render persistent disk envs point to a
    durable directory. On Windows the default root is D:\\SharipovAI\\data so
    project state survives code updates and stays on the dedicated data drive.
    Non-Windows local development keeps existing relative data/ paths.
    """

    explicit = os.getenv(env_name)
    if explicit:
        return Path(explicit)
    base = os.getenv("SHARIPOVAI_DATA_DIR") or os.getenv("RENDER_DISK_PATH")
    if base:
        return Path(base) / Path(default_relative).name
    if os.name == "nt":
        return Path(r"D:\SharipovAI\data") / Path(default_relative).name
    return Path(default_relative)
