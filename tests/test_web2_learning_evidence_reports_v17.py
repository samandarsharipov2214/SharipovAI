from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "dashboard" / "static" / "web2"


def test_learning_evidence_reports_use_canonical_owner() -> None:
    index = (WEB / "index.html").read_text(encoding="utf-8")
    assert "learning_evidence_reports_v17.css" in index
    assert "canonical_pages_v45.js" in index
    assert "learning_evidence_reports_v17.js" not in index


def test_canonical_owner_uses_real_api_routes() -> None:
    js = (WEB / "canonical_pages_v45.js").read_text(encoding="utf-8")
    for route in (
        "/api/learning-os/status",
        "/api/evidence-vault/recent",
        "/api/ai-control-center/daily-report",
        "/api/system/runtime-truth",
        "/api/autonomous-paper/events",
    ):
        assert route in js
    assert "/api/run" not in js
    assert "/api/ai-bots" not in js


def test_canonical_owner_covers_learning_evidence_and_reports() -> None:
    js = (WEB / "canonical_pages_v45.js").read_text(encoding="utf-8")
    for label in (
        "Центр обучения",
        "Хранилище доказательств",
        "Отчёты",
        "Evidence Vault",
        "канонического paper runtime",
    ):
        assert label in js
    assert "Math.random" not in js
