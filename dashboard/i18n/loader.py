"""Internationalization loader for the SharipovAI OS web UI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_LANGUAGE: str = "ru"
SUPPORTED_LANGUAGES: frozenset[str] = frozenset({"ru", "en", "uz"})
_I18N_DIR = Path(__file__).parent


def normalize_language(language: str | None) -> str:
    """Normalize a requested language or ``Accept-Language`` value.

    Regional locale tags are mapped onto the three canonical UI catalogs. When
    several language ranges are supplied, the first supported range with a
    non-zero quality value wins. Unknown or empty input falls back to Russian.

    Args:
        language: Requested language code or ``Accept-Language`` value.

    Returns:
        Canonical supported language code, falling back to Russian.
    """

    if not language:
        return DEFAULT_LANGUAGE

    for raw_range in str(language).split(","):
        parts = [part.strip() for part in raw_range.split(";") if part.strip()]
        if not parts:
            continue

        quality = 1.0
        for parameter in parts[1:]:
            name, separator, value = parameter.partition("=")
            if separator and name.strip().lower() == "q":
                try:
                    quality = float(value.strip())
                except ValueError:
                    quality = 0.0
                break
        if quality <= 0:
            continue

        locale = parts[0].lower().replace("_", "-")
        primary_language = locale.split("-", 1)[0]
        if primary_language in SUPPORTED_LANGUAGES:
            return primary_language

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
