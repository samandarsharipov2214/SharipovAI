from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "dashboard" / "static" / "web2"


def test_ai_center_assets_are_connected() -> None:
    index = (WEB / "index.html").read_text(encoding="utf-8")
    assert "/static/web2/ai_center_v44.js?" in index
    assert "/static/web2/ai_center_v14.css?" in index
    assert index.index("ai_center_v14.css") < index.index("ai_center_v44.js")
    assert "ai_center_v14.js" not in index


def test_ai_center_uses_canonical_runtime_truth_only() -> None:
    js = (WEB / "ai_center_v44.js").read_text(encoding="utf-8")
    assert "/api/system/runtime-truth" in js
    assert "/api/ai-bots" not in js
    assert "/api/run" not in js
    assert "Math.random" not in js
    assert "healthy" in js
    assert "degraded" in js
    assert "blocked" in js


def test_ai_center_distinguishes_registry_from_health() -> None:
    js = (WEB / "ai_center_v44.js").read_text(encoding="utf-8")
    required = (
        "Архитектурный реестр",
        "не является health-оценкой",
        "Evidence",
        "Blockers",
        "Recovery",
        "organ_count",
    )
    for marker in required:
        assert marker in js


def test_ai_center_reuses_responsive_ai_styles() -> None:
    css = (WEB / "ai_center_v14.css").read_text(encoding="utf-8")
    assert "@media(max-width:720px)" in css
    assert ".ai14-modal" in css
    assert ".ai14-nodes" in css
