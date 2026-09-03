from __future__ import annotations

from typing import Any

import agent_intelligence


def test_openrouter_completion_uses_role_and_grounded_web_citations(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {
                "choices": [
                    {
                        "message": {
                            "content": "Дельфин обычно весит по-разному в зависимости от вида.",
                            "annotations": [
                                {
                                    "type": "url_citation",
                                    "url_citation": {
                                        "url": "https://example.org/dolphin",
                                        "title": "Dolphin facts",
                                    },
                                }
                            ],
                        }
                    }
                ]
            }

    def fake_post(url: str, **kwargs: Any) -> Response:
        captured["url"] = url
        captured.update(kwargs)
        return Response()

    monkeypatch.setenv("AGENT_LLM_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("AGENT_LLM_API_KEY", "not-a-real-key")
    monkeypatch.setenv("AGENT_LLM_MODEL", "qwen/qwen-2.5-7b-instruct")
    monkeypatch.setattr(agent_intelligence.httpx, "post", fake_post)

    result = agent_intelligence.answer_with_intelligence(
        agent_id="risk_engine",
        agent_name="Risk Engine",
        role="Контроль риска.",
        question="Сколько весит дельфин?",
        state={"execution_kill_switch": True},
    )

    assert result.status == "ok"
    assert result.grounded is True
    assert result.citations == (("Dolphin facts", "https://example.org/dolphin"),)
    assert "Источники" in result.text
    request = captured["json"]
    assert request["tools"] == [{"type": "openrouter:web_search", "max_total_results": 5}]
    assert "Risk Engine" in request["messages"][0]["content"]
    assert "не связан" in request["messages"][0]["content"]
    assert "execution_kill_switch" in request["messages"][-1]["content"]


def test_provider_failure_is_explicit_and_never_uses_fake_web_answer(monkeypatch) -> None:
    monkeypatch.delenv("AGENT_LLM_API_KEY", raising=False)
    monkeypatch.delenv("MEMORY_LLM_API_KEY", raising=False)

    result = agent_intelligence.answer_with_intelligence(
        agent_id="general_controller",
        agent_name="General Controller",
        role="Координация.",
        question="Что нового сегодня?",
        state={},
    )

    assert result.status == "unavailable"
    assert result.grounded is False
    assert result.citations == ()
    assert "не настроен" in result.error


def test_untrusted_state_is_bounded_and_secrets_are_not_sent(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {"choices": [{"message": {"content": "Безопасный ответ."}}]}

    def fake_post(_url: str, **kwargs: Any) -> Response:
        captured.update(kwargs)
        return Response()

    monkeypatch.setenv("AGENT_LLM_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("AGENT_LLM_API_KEY", "not-a-real-key")
    monkeypatch.setenv("AGENT_LLM_MODEL", "qwen/qwen-2.5-7b-instruct")
    monkeypatch.setattr(agent_intelligence.httpx, "post", fake_post)

    result = agent_intelligence.answer_with_intelligence(
        agent_id="general_controller",
        agent_name="General Controller",
        role="Координация.",
        question="status",
        state={"api_key": "must-not-leak", "equity": 100, "nested": {"token": "nope"}},
    )

    assert result.status == "ok"
    serialized = str(captured["json"])
    assert "must-not-leak" not in serialized
    assert "nope" not in serialized
    assert "equity" in serialized
