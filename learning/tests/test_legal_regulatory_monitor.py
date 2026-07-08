from __future__ import annotations

from fastapi.testclient import TestClient

from learning.legal_monitor_app import app
from learning.legal_regulatory_monitor import evaluate_legal_change, legal_alert_summary, legal_monitor_plan, legal_monitor_policy


def test_legal_monitor_plan_contains_regulatory_sources() -> None:
    plan = legal_monitor_plan("us")

    assert plan["status"] == "ok"
    assert "sec.gov" in plan["sources"]
    assert "cftc.gov" in plan["sources"]
    assert "crypto_regulation" in {task["topic"] for task in plan["tasks"]}
    assert all(task["output"] == "legal_change_summary_risk_alert_controller_advice" for task in plan["tasks"])


def test_legal_monitor_policy_marks_not_legal_advice() -> None:
    policy = legal_monitor_policy()

    assert policy["not_legal_advice"] is True
    assert "block_action" in policy["controller_actions"]
    assert any("Do not treat social media as law" in rule for rule in policy["rules"])


def test_critical_official_change_blocks_action() -> None:
    result = evaluate_legal_change(
        {
            "title": "Official crypto ban",
            "topic": "crypto_regulation",
            "source_domain": "sec.gov",
            "source_type": "regulator_docs",
            "summary": "New official rule: crypto exchange activity is illegal for this category and must be banned.",
        }
    )

    assert result["status"] == "ok"
    assert result["official_source"] is True
    assert result["severity"] == "critical"
    assert result["general_controller_advice"]["action"] == "block_action"
    assert "security_guard" in result["affected_bots"]


def test_unofficial_regulatory_news_requires_watch_or_caution() -> None:
    result = evaluate_legal_change(
        {
            "title": "Possible crypto proposal",
            "topic": "crypto_regulation",
            "source_domain": "news.example",
            "source_type": "legal_news",
            "summary": "A proposal may introduce new rule for crypto exchanges.",
        }
    )

    assert result["status"] == "ok"
    assert result["official_source"] is False
    assert result["severity"] in {"watch", "caution"}
    assert result["general_controller_advice"]["action"] in {"watch", "caution"}


def test_legal_alert_summary_uses_highest_action() -> None:
    summary = legal_alert_summary(
        [
            {"title": "Minor warning", "topic": "consumer_protection", "source_domain": "news.example", "source_type": "legal_news", "summary": "warning about scams"},
            {"title": "Official ban", "topic": "crypto_regulation", "source_domain": "cftc.gov", "source_type": "regulator_docs", "summary": "official ban and illegal activity"},
        ]
    )

    assert summary["status"] == "ok"
    assert summary["highest_severity"] == "critical"
    assert summary["controller_action"] == "block_action"


def test_legal_monitor_api() -> None:
    client = TestClient(app)

    plan = client.get("/api/legal/plan?region=eu")
    assert plan.status_code == 200
    assert "esma.europa.eu" in plan.json()["sources"]

    evaluated = client.post(
        "/api/legal/evaluate",
        json={"title": "KYC guidance", "topic": "aml_kyc", "source_domain": "fatf-gafi.org", "source_type": "official", "summary": "New guidance for AML KYC crypto assets."},
    )
    assert evaluated.status_code == 200
    assert evaluated.json()["status"] == "ok"
