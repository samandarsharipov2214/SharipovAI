"""Regression contract for the Paper all-trades DOM renderer."""
from __future__ import annotations

from pathlib import Path


_SOURCE = Path(__file__).resolve().parents[1] / "static" / "mini-app-all-trades.js"


def test_all_trades_renderer_avoids_html_string_sinks() -> None:
    """Server/runtime trade fields must be rendered as text, never parsed HTML."""

    source = _SOURCE.read_text(encoding="utf-8")

    assert ".innerHTML" not in source
    assert ".outerHTML" not in source
    assert "insertAdjacentHTML" not in source
    assert "eval(" not in source


def test_all_trades_renderer_uses_text_dom_primitives() -> None:
    """Keep the renderer on DOM/text primitives when future fields are added."""

    source = _SOURCE.read_text(encoding="utf-8")

    assert "textContent" in source
    assert "createTextNode" in source
    assert "replaceChildren" in source
