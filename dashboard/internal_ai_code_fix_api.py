"""Local service endpoint for generating bounded unified-diff repair candidates."""
from __future__ import annotations

import os
import re
import secrets
from typing import Any, Literal

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .gemini_chat_api import (
    _GEMINI_ENDPOINT,
    _bounded_float,
    _bounded_int,
    _extract_text,
    _model_name,
)
from .internal_service_auth import require_internal_service

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SYSTEM_PROMPT = """
You are SharipovAI Code Repair Engine. Return exactly one unified diff and nothing else.
The patch must be minimal, deterministic and limited to the failure described by the caller.
Use paths relative to the repository root. Do not modify CONSTITUTION.md, Dockerfile,
requirements.txt, .github/, deploy/ or execution/. Do not rename files, create symlinks,
add binary data, weaken or delete tests, disable authentication, bypass Security Guard,
execute shell/network commands, expose secrets, enable real orders, or change financial
safety limits. Preserve public APIs unless the failure requires a compatible correction.
Include or update focused tests when safe. The result must start with 'diff --git '.
If no safe patch can be produced, return an empty string.
""".strip()


class InternalCodeFixHistoryMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=12_000)


class InternalCodeFixRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    message: str = Field(min_length=1, max_length=24_000)
    history: list[InternalCodeFixHistoryMessage] = Field(default_factory=list, max_length=20)
    request_sha256: str

    @field_validator("request_sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        normalized = value.lower()
        if not _SHA256.fullmatch(normalized):
            raise ValueError("request_sha256 must be 64 lowercase hexadecimal characters")
        return normalized


def _contents(payload: InternalCodeFixRequest) -> list[dict[str, Any]]:
    items = [
        {
            "role": "model" if item.role == "assistant" else "user",
            "parts": [{"text": item.content}],
        }
        for item in payload.history
    ]
    items.append({
        "role": "user",
        "parts": [{"text": f"Request SHA-256: {payload.request_sha256}\n\nFailure:\n{payload.message}"}],
    })
    return items


def install_internal_ai_code_fix_api(app: FastAPI) -> None:
    if getattr(app.state, "internal_ai_code_fix_api_installed", False):
        return
    app.state.internal_ai_code_fix_api_installed = True

    @app.post("/internal/ai/code-fix", include_in_schema=False)
    async def internal_ai_code_fix(
        payload: InternalCodeFixRequest,
        request: Request,
        response: Response,
    ) -> dict[str, str]:
        require_internal_service(request)
        api_key = os.getenv("GEMINI_API_KEY", "").strip() or os.getenv("GOOGLE_API_KEY", "").strip()
        if not api_key:
            raise HTTPException(status_code=503, detail={"status": "gemini_not_configured"})

        model = _model_name()
        request_id = f"fix-{secrets.token_hex(8)}"
        provider_payload = {
            "systemInstruction": {"parts": [{"text": _SYSTEM_PROMPT}]},
            "contents": _contents(payload),
            "generationConfig": {
                "temperature": 0.05,
                "maxOutputTokens": _bounded_int("GEMINI_CODE_FIX_MAX_OUTPUT_TOKENS", 4096, 512, 8192),
            },
        }
        timeout = _bounded_float("GEMINI_API_TIMEOUT_SECONDS", 30.0, 5.0, 60.0)
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout), follow_redirects=False) as client:
                provider_response = await client.post(
                    f"{_GEMINI_ENDPOINT}/models/{model}:generateContent",
                    headers={
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                        "X-Goog-Api-Key": api_key,
                    },
                    json=provider_payload,
                )
                provider_response.raise_for_status()
                provider_data = provider_response.json()
        except httpx.TimeoutException as exc:
            raise HTTPException(status_code=504, detail={"status": "gemini_timeout", "request_id": request_id}) from exc
        except httpx.HTTPStatusError as exc:
            status = 429 if exc.response.status_code == 429 else 502
            raise HTTPException(status_code=status, detail={"status": "gemini_provider_error", "request_id": request_id}) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(status_code=502, detail={"status": "gemini_unavailable", "request_id": request_id}) from exc

        text = _extract_text(provider_data).strip()
        if text.startswith("```diff") and text.endswith("```"):
            text = text[7:-3].strip()
        if text and not text.startswith("diff --git "):
            raise HTTPException(status_code=502, detail={"status": "invalid_patch_response", "request_id": request_id})

        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Request-Id"] = request_id
        return {"text": text, "model": model, "request_id": request_id}


__all__ = [
    "InternalCodeFixHistoryMessage",
    "InternalCodeFixRequest",
    "install_internal_ai_code_fix_api",
]
