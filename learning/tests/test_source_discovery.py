from __future__ import annotations

from fastapi.testclient import TestClient

from learning.source_discovery import discovery_plan, rank_source_candidates, source_policy, validate_source_candidate
from learning.source_discovery_app import app


def test_discovery_plan_for_risk_engine_contains_search_tasks() -> None:
    plan = discovery_plan("risk_engine")

    assert plan["status"] == "ok"
    bot_plan = plan["plans"][0]
    assert bot_plan["status"] == "ok"
    assert bot_plan["bot"] == "risk_engine"
    assert "risk" in bot_plan["domains"]
    assert bot_plan["search_tasks"]
    assert all(task["output"] == "metadata_summary_rules_exam" for task in bot_plan["search_tasks"])


def test_source_policy_blocks_pirated_full_text() -> None:
    policy = source_policy()

    assert "pirated_book" in policy["blocked_source_classes"]
    assert "official" in policy["allowed_source_classes"]
    assert any("Never store full copyrighted" in rule for rule in policy["rules"])


def test_validate_source_candidate_accepts_official_source() -> None:
    result = validate_source_candidate(
        {
            "title": "SEC investor education",
            "url": "https://www.sec.gov/education",
            "domain": "sec.gov",
            "source_class": "regulator_docs",
        }
    )

    assert result["status"] == "accepted"
    assert result["trust_score"] >= 90


def test_validate_source_candidate_rejects_pirated_book() -> None:
    result = validate_source_candidate(
        {
            "title": "Some paid trading book full PDF",
            "url": "https://example.com/book.pdf",
            "domain": "example.com",
            "source_class": "pirated_book",
        }
    )

    assert result["status"] == "rejected"
    assert result["reason"] == "blocked_source_class"


def test_rank_source_candidates_puts_trusted_sources_first() -> None:
    ranked = rank_source_candidates(
        [
            {"title": "Random blog", "url": "https://blog.example/x", "domain": "blog.example", "source_class": "article"},
            {"title": "SEC guide", "url": "https://sec.gov/x", "domain": "sec.gov", "source_class": "regulator_docs"},
        ]
    )

    assert ranked[0]["title"] == "SEC guide"
    assert ranked[0]["validation"]["status"] == "accepted"
    assert ranked[1]["validation"]["status"] == "needs_review"


def test_source_discovery_api() -> None:
    client = TestClient(app)

    plan_response = client.get("/api/learning/discovery/plan/news_agent")
    assert plan_response.status_code == 200
    assert plan_response.json()["plans"][0]["bot"] == "news_agent"

    validate_response = client.post(
        "/api/learning/discovery/validate",
        json={"title": "Bitcoin whitepaper", "url": "https://bitcoin.org/bitcoin.pdf", "domain": "bitcoin.org", "source_class": "whitepaper"},
    )
    assert validate_response.status_code == 200
    assert validate_response.json()["status"] == "accepted"
