"""AI-assisted repair pipeline with exact/similar reuse, sandboxing and tests."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import httpx

from development_control.security_guard import SecurityGuard


@dataclass(slots=True)
class FailureCase:
    message: str
    history: list[dict[str, str]] = field(default_factory=list)
    targeted_tests: list[str] = field(default_factory=list)
    request_sha256: str = ""

    def digest(self) -> str:
        return self.request_sha256 or hashlib.sha256(self.message.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class ValidatedPatchCandidate:
    accepted: bool
    patch: str = ""
    source: str = "none"
    reasons: list[str] = field(default_factory=list)
    model: str = ""
    request_id: str = ""
    sandbox_path: str = ""
    tests: list[str] = field(default_factory=list)
    test_output: str = ""


class AIFixer:
    def __init__(
        self,
        *,
        repo_root: str | Path = "/app",
        fixes_dir: str | Path | None = None,
        endpoint: str | None = None,
        service_token: str | None = None,
        timeout_seconds: float = 60.0,
        similarity_threshold: float = 0.82,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.fixes_dir = Path(fixes_dir or self.repo_root / "agent_fixes")
        self.endpoint = endpoint or os.getenv("SHARIPOVAI_CODE_FIX_ENDPOINT", "http://127.0.0.1:8000/internal/ai/code-fix")
        self.service_token = service_token or os.getenv("SHARIPOVAI_SERVICE_TOKEN", "")
        self.timeout_seconds = timeout_seconds
        self.similarity_threshold = similarity_threshold
        self.guard = SecurityGuard()

    def attempt(self, failure: FailureCase) -> ValidatedPatchCandidate:
        digest = failure.digest()
        exact = self._exact_patch(digest)
        if exact:
            return self._validate_apply_test(exact, failure, source="agent_fixes:exact")

        similar = self._similar_patch(failure.message)
        if similar:
            candidate = self._validate_apply_test(similar, failure, source="agent_fixes:similar")
            if candidate.accepted:
                return candidate

        generated = self._request_patch(failure, digest)
        if not generated[0]:
            return ValidatedPatchCandidate(accepted=False, source="gemini", reasons=[generated[3] or "empty patch"], model=generated[1], request_id=generated[2])
        return self._validate_apply_test(generated[0], failure, source="gemini", model=generated[1], request_id=generated[2])

    def _exact_patch(self, digest: str) -> str:
        for suffix in (".patch", ".diff"):
            path = self.fixes_dir / f"{digest}{suffix}"
            if path.is_file():
                return path.read_text(encoding="utf-8")
        return ""

    def _similar_patch(self, message: str) -> str:
        best_score = 0.0
        best_patch = ""
        if not self.fixes_dir.is_dir():
            return ""
        for metadata in self.fixes_dir.glob("*.json"):
            try:
                record = json.loads(metadata.read_text(encoding="utf-8"))
                known = str(record.get("message", ""))
                patch_name = str(record.get("patch", ""))
                score = SequenceMatcher(None, message.lower(), known.lower()).ratio()
                patch_path = self.fixes_dir / patch_name
                if score > best_score and patch_path.is_file():
                    best_score, best_patch = score, patch_path.read_text(encoding="utf-8")
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
        return best_patch if best_score >= self.similarity_threshold else ""

    def _request_patch(self, failure: FailureCase, digest: str) -> tuple[str, str, str, str]:
        if not self.service_token:
            return "", "", "", "SHARIPOVAI_SERVICE_TOKEN is not configured"
        payload = {"message": failure.message, "history": failure.history, "request_sha256": digest}
        try:
            with httpx.Client(timeout=self.timeout_seconds, follow_redirects=False) as client:
                response = client.post(self.endpoint, headers={"X-SharipovAI-Service-Token": self.service_token}, json=payload)
                response.raise_for_status()
                data = response.json()
            return str(data.get("text", "")), str(data.get("model", "")), str(data.get("request_id", "")), ""
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            return "", "", "", f"internal code-fix request failed: {type(exc).__name__}: {exc}"

    def _validate_apply_test(self, patch: str, failure: FailureCase, *, source: str, model: str = "", request_id: str = "") -> ValidatedPatchCandidate:
        verdict = self.guard.check(patch)
        if not verdict.allowed:
            return ValidatedPatchCandidate(False, patch, source, verdict.reasons, model, request_id)

        sandbox_parent = Path(os.getenv("SHARIPOVAI_FIX_SANDBOX_ROOT", tempfile.gettempdir()))
        sandbox_parent.mkdir(parents=True, exist_ok=True)
        sandbox = Path(tempfile.mkdtemp(prefix="sharipovai-fix-", dir=sandbox_parent))
        workspace = sandbox / "repo"
        shutil.copytree(self.repo_root, workspace, ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", ".venv", "deployment_control"))
        patch_file = sandbox / "candidate.patch"
        patch_file.write_text(patch, encoding="utf-8")

        applied = subprocess.run(["git", "apply", "--check", str(patch_file)], cwd=workspace, text=True, capture_output=True, timeout=30)
        if applied.returncode != 0:
            return ValidatedPatchCandidate(False, patch, source, ["git apply --check failed"], model, request_id, str(workspace), test_output=(applied.stdout + applied.stderr)[-8000:])
        apply_result = subprocess.run(["git", "apply", str(patch_file)], cwd=workspace, text=True, capture_output=True, timeout=30)
        if apply_result.returncode != 0:
            return ValidatedPatchCandidate(False, patch, source, ["git apply failed"], model, request_id, str(workspace), test_output=(apply_result.stdout + apply_result.stderr)[-8000:])

        tests = self._targeted_tests(failure, patch)
        command = ["python", "-m", "pytest", "-q", *tests]
        result = subprocess.run(command, cwd=workspace, text=True, capture_output=True, timeout=int(os.getenv("SHARIPOVAI_FIX_TEST_TIMEOUT", "180")))
        output = (result.stdout + "\n" + result.stderr)[-16000:]
        if result.returncode != 0:
            return ValidatedPatchCandidate(False, patch, source, ["targeted tests failed"], model, request_id, str(workspace), tests, output)
        return ValidatedPatchCandidate(True, patch, source, [], model, request_id, str(workspace), tests, output)

    def _targeted_tests(self, failure: FailureCase, patch: str) -> list[str]:
        if failure.targeted_tests:
            return failure.targeted_tests
        paths: list[str] = []
        for line in patch.splitlines():
            if line.startswith("+++ b/"):
                changed = line[6:].strip()
                if changed.startswith("tests/") and changed.endswith(".py"):
                    paths.append(changed)
        return paths or ["tests"]


__all__ = ["AIFixer", "FailureCase", "ValidatedPatchCandidate"]
