from __future__ import annotations

from fastapi.testclient import TestClient

from learning.financial_knowledge_library import BOT_DOMAIN_MAP, bot_curriculum, knowledge_manifest, minimum_rules_for_domains
from learning.learning_app import app


def test_financial_knowledge_manifest_has_core_domains_and_sources() -> None:
    manifest = knowledge_manifest()

    assert manifest["status"] == "ok"
    assert "crypto" in manifest["domains"]
    assert "stocks" in manifest["domains"]
    assert "exchanges" in manifest["domains"]
    assert "financial_institutions" in manifest["domains"]
    assert len(manifest["source_registry"]) >= 8
    assert len(manifest["core_concepts"]) >= 10


def test_every_bot_has_financial_curriculum() -> None:
    for bot in BOT_DOMAIN_MAP:
        curriculum = bot_curriculum(bot)
        assert curriculum["status"] == "ok"
        assert curriculum["domains"]
        assert curriculum["concepts"]
        assert curriculum["sources"]
        assert curriculum["minimum_rules"]


def test_news_agent_learns_crypto_stocks_macro_and_regulation() -> None:
    curriculum = bot_curriculum("news_agent")

    assert set(curriculum["domains"]) == {"crypto", "stocks", "macro", "regulation"}
    assert any(source["domain"] == "regulation" for source in curriculum["sources"])
    assert any("официального источника" in rule.lower() for rule in curriculum["minimum_rules"])


def test_risk_rules_include_crypto_and_exchange_risk() -> None:
    rules = minimum_rules_for_domains(["crypto", "exchanges", "risk"])
    joined = "\n".join(rules).lower()

    assert "ликвидность" in joined
    assert "стакан" in joined
    assert "высоком риске" in joined


def test_financial_knowledge_api_manifest() -> None:
    client = TestClient(app)

    response = client.get("/api/learning/finance/manifest")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert "bot_domain_map" in payload


def test_financial_knowledge_api_bot_curriculum() -> None:
    client = TestClient(app)

    response = client.get("/api/learning/finance/bots/risk_engine")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert "risk" in payload["domains"]
    assert any("риск" in rule.lower() for rule in payload["minimum_rules"])
