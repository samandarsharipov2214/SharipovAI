"""Optional LLM fact extraction and embeddings, disabled unless explicitly configured."""
from __future__ import annotations

import json
from typing import Any, Protocol, Sequence

import httpx
from pydantic import BaseModel, ConfigDict, Field

from .config import MemorySettings
from .models import RawLog


class ExtractedFact(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    content: str = Field(min_length=1, max_length=20_000)
    background: str = Field(default="", max_length=20_000)
    fact_type: str = Field(default="work_fact", min_length=1, max_length=64)
    priority: int = Field(default=50, ge=0, le=100)


class JSONCompletionClient(Protocol):
    def complete_json(self, *, system: str, user: str) -> Any: ...


class EmbeddingProvider(Protocol):
    def embed(self, text: str) -> Sequence[float]: ...


class OpenAICompatibleJSONClient:
    """Small OpenAI-compatible JSON client with no calls until extraction is enabled."""

    def __init__(self, *, base_url: str, api_key: str, model: str, timeout: float = 30.0) -> None:
        if not base_url or not api_key or not model:
            raise ValueError("base_url, api_key and model are required")
        self.endpoint = _endpoint(base_url, "chat/completions")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def complete_json(self, *, system: str, user: str) -> Any:
        response = httpx.post(
            self.endpoint,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={
                "model": self.model,
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        content = payload["choices"][0]["message"]["content"]
        return json.loads(content) if isinstance(content, str) else content


class OpenAICompatibleEmbeddingProvider:
    def __init__(self, *, base_url: str, api_key: str, model: str, timeout: float = 30.0) -> None:
        if not base_url or not api_key or not model:
            raise ValueError("base_url, api_key and model are required")
        self.endpoint = _endpoint(base_url, "embeddings")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def embed(self, text: str) -> Sequence[float]:
        response = httpx.post(
            self.endpoint,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={"model": self.model, "input": text},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        vector = payload["data"][0]["embedding"]
        if not isinstance(vector, list) or not vector or len(vector) > 8192:
            raise ValueError("embedding provider returned an invalid vector")
        return [float(item) for item in vector]


class FactExtractor:
    """Convert one raw log to bounded facts; it never activates memory."""

    def __init__(self, settings: MemorySettings, client: JSONCompletionClient | None = None) -> None:
        self.settings = settings
        self.client = client

    @classmethod
    def from_settings(cls, settings: MemorySettings) -> "FactExtractor":
        client: JSONCompletionClient | None = None
        if settings.extraction_enabled and settings.llm_base_url and settings.llm_api_key and settings.llm_model:
            client = OpenAICompatibleJSONClient(
                base_url=settings.llm_base_url,
                api_key=settings.llm_api_key,
                model=settings.llm_model,
            )
        return cls(settings, client)

    def extract(self, raw: RawLog) -> list[ExtractedFact]:
        if not self.settings.enabled or not self.settings.extraction_enabled:
            return []
        if self.client is None:
            raise RuntimeError("memory extraction is enabled but MEMORY_LLM_* is incomplete")
        text = raw.content[: self.settings.max_input_chars]
        payload = self.client.complete_json(
            system=(
                "Extract only durable, work-relevant facts from the supplied SharipovAI event. "
                "Do not invent values, credentials, prices, balances, permissions or trading authority. "
                "Return JSON object {\"facts\": [{\"content\": str, \"background\": str, "
                "\"fact_type\": one of work_fact/work_task/work_method/work_artifact/instruction, "
                "\"priority\": integer 0..100}]}. Return an empty facts list when nothing is durable."
            ),
            user=json.dumps(
                {
                    "agent_id": raw.agent_id,
                    "session_id": raw.session_id,
                    "source_ref": raw.source_ref,
                    "message_role": raw.message_role,
                    "content": text,
                },
                ensure_ascii=False,
            ),
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("facts"), list):
            raise ValueError("memory extractor returned an invalid JSON object")
        facts: list[ExtractedFact] = []
        for value in payload["facts"][:20]:
            facts.append(ExtractedFact.model_validate(value))
        return facts


def embedding_provider_from_settings(settings: MemorySettings) -> EmbeddingProvider | None:
    if not (
        settings.enabled
        and settings.embedding_base_url
        and settings.embedding_api_key
        and settings.embedding_model
    ):
        return None
    return OpenAICompatibleEmbeddingProvider(
        base_url=settings.embedding_base_url,
        api_key=settings.embedding_api_key,
        model=settings.embedding_model,
    )


def _endpoint(base_url: str, suffix: str) -> str:
    clean = base_url.rstrip("/")
    if clean.endswith(f"/{suffix}"):
        return clean
    return f"{clean}/{suffix}"


__all__ = [
    "EmbeddingProvider",
    "ExtractedFact",
    "FactExtractor",
    "JSONCompletionClient",
    "OpenAICompatibleEmbeddingProvider",
    "OpenAICompatibleJSONClient",
    "embedding_provider_from_settings",
]
