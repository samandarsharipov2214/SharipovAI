from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB2 = ROOT / "dashboard" / "static" / "web2"
INDEX = WEB2 / "index.html"


def _loaded_javascript() -> list[str]:
    html = INDEX.read_text(encoding="utf-8")
    return re.findall(r'<script[^>]+src="/static/web2/([^"?]+)', html)


def test_pr246_loaded_javascript_is_canonical_and_legacy_free() -> None:
    loaded = _loaded_javascript()
    assert "navigation_coordinator_v44.js" in loaded
    assert "web2_shell_v44.js" in loaded
    assert "overview_runtime_v44.js" in loaded
    assert "canonical_pages_v45.js" in loaded
    assert "ai_center_v44.js" in loaded
    assert "system_status_v44.js" in loaded

    sources = "\n".join((WEB2 / name).read_text(encoding="utf-8") for name in loaded)
    for endpoint in (
        "/api/run",
        "/api/ai-bots",
        "/api/virtual-account/state",
        "/api/virtual-account/trades",
        "/api/paper-activity/state",
        "/api/paper-activity/trades",
    ):
        assert endpoint not in sources
    assert "/api/system/runtime-truth" in sources
    assert "CouncilAuthorizedPaperLoop" in sources
    assert "real_orders_blocked" in sources
