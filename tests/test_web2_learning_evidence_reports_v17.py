from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "dashboard" / "static" / "web2"


def test_v17_files_are_connected() -> None:
    index = (WEB / "index.html").read_text(encoding="utf-8")
    assert "learning_evidence_reports_v17.css" in index
    assert "learning_evidence_reports_v17.js" in index


def test_v17_uses_real_api_routes() -> None:
    js = (WEB / "learning_evidence_reports_v17.js").read_text(encoding="utf-8")
    for route in (
        "/api/learning-os/status",
        "/api/evidence-vault/recent",
        "/api/ai-control-center/daily-report",
        "/api/run",
        "/api/exchange/account/snapshot",
        "/api/ai-bots",
    ):
        assert route in js


def test_v17_covers_three_sections_and_truth_rules() -> None:
    js = (WEB / "learning_evidence_reports_v17.js").read_text(encoding="utf-8")
    assert "Центр обучения" in js
    assert "Хранилище доказательств" in js
    assert "Отчёты" in js
    assert "С доказательством" in js
    assert "Без прогнозных цифр" in js
    assert "Math.random" not in js
    assert "demo" not in js.lower()
