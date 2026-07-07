"""Internationalization loader for the SharipovAI OS web UI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_LANGUAGE: str = "ru"
SUPPORTED_LANGUAGES: frozenset[str] = frozenset({"ru", "en", "uz"})
_I18N_DIR = Path(__file__).parent


def normalize_language(language: str | None) -> str:
    """Normalize a requested language code.

    Args:
        language: Requested language code.

    Returns:
        Supported language code, falling back to Russian.
    """

    if language in SUPPORTED_LANGUAGES:
        return language
    return DEFAULT_LANGUAGE


def load_translations(language: str | None) -> dict[str, str]:
    """Load translations for a supported language.

    Args:
        language: Requested language code.

    Returns:
        Translation mapping.
    """

    normalized_language = normalize_language(language)
    path = _I18N_DIR / f"{normalized_language}.json"
    with path.open("r", encoding="utf-8") as file:
        payload: dict[str, Any] = json.load(file)
    return {str(key): str(value) for key, value in payload.items()}
