from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from starlette.requests import Request

from dashboard.internal_ai_code_fix_api import InternalCodeFixRequest, install_internal_ai_code_fix_api
from dashboard.internal_service_auth import require_internal_service
from development_control.security_guard import validate_patch
from tools.ai_fixer import AIFixer, FailureCase


def _request(host: str, token: str = "") -> Request:
    headers = []
    if token:
        headers.append((b"x-sharipovai-service-token", token.encode()))
    return Request({
        "type": "http",
        "method": "POST",
        "path": "/internal/ai/code-fix",
        "headers": headers,
        "client": (host, 12345),
        "server": ("127.0.0.1", 8000),
        "scheme": "http",
        "query_string": b"",
    })


def test_internal_service_requires_loopback_and_token(monkeypatch):
    monkeypatch.setenv("SHARIPOVAI_SERVICE_TOKEN", "secret-value")
    require_internal_service(_request("127.0.0.1", "secret-value"))
    require_internal_service(_request("::1", "secret-value"))

    with pytest.raises(HTTPException) as remote:
        require_internal_service(_request("172.18.0.4", "secret-value"))
    assert remote.value.status_code == 403

    with pytest.raises(HTTPException) as bad_token:
        require_internal_service(_request("127.0.0.1", "wrong"))
    assert bad_token.value.status_code == 401


def test_internal_request_sha_and_route_visibility():
    digest = hashlib.sha256(b"failure").hexdigest()
    payload = InternalCodeFixRequest(message="failure", history=[], request_sha256=digest)
    assert payload.request_sha256 == digest
    with pytest.raises(ValueError):
        InternalCodeFixRequest(message="failure", history=[], request_sha256="bad")

    app = FastAPI()
    install_internal_ai_code_fix_api(app)
    install_internal_ai_code_fix_api(app)
    paths = [getattr(route, "path", "") for route in app.routes]
    assert paths.count("/internal/ai/code-fix") == 1
    assert "/internal/ai/code-fix" not in app.openapi().get("paths", {})


def test_security_guard_rejects_protected_and_dangerous_patches():
    protected = """diff --git a/Dockerfile b/Dockerfile
--- a/Dockerfile
+++ b/Dockerfile
@@ -1 +1 @@
-FROM python
+FROM alpine
"""
    assert not validate_patch(protected).allowed

    dangerous = """diff --git a/module.py b/module.py
--- a/module.py
+++ b/module.py
@@ -1 +1,2 @@
 value = 1
+os.system('whoami')
"""
    verdict = validate_patch(dangerous)
    assert not verdict.allowed
    assert any("dangerous construct" in reason for reason in verdict.reasons)


def test_ai_fixer_exact_and_similarity_lookup(tmp_path: Path):
    fixes = tmp_path / "agent_fixes"
    fixes.mkdir()
    message = "fix exact failure"
    digest = hashlib.sha256(message.encode()).hexdigest()
    patch = """diff --git a/module.py b/module.py
--- a/module.py
+++ b/module.py
@@ -1 +1 @@
-old = 1
+old = 2
"""
    (fixes / f"{digest}.patch").write_text(patch, encoding="utf-8")
    similar_patch = fixes / "similar.patch"
    similar_patch.write_text(patch, encoding="utf-8")
    (fixes / "similar.json").write_text(json.dumps({"message": "another known failure", "patch": "similar.patch"}), encoding="utf-8")

    fixer = AIFixer(repo_root=tmp_path, fixes_dir=fixes, service_token="token")
    assert fixer._exact_patch(digest) == patch
    assert fixer._similar_patch("another known failure") == patch


def test_ai_fixer_rejects_patch_before_sandbox(tmp_path: Path):
    fixer = AIFixer(repo_root=tmp_path, service_token="token")
    failure = FailureCase(message="unsafe")
    candidate = fixer._validate_apply_test(
        """diff --git a/requirements.txt b/requirements.txt
--- a/requirements.txt
+++ b/requirements.txt
@@ -1 +1 @@
-fastapi
+malware
""",
        failure,
        source="test",
    )
    assert candidate.accepted is False
    assert any("protected path" in reason for reason in candidate.reasons)
    assert candidate.sandbox_path == ""
