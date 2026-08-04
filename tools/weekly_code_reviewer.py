#!/usr/bin/env python3
"""Weekly, owner-approved code review proposals for SharipovAI.

The reviewer selects one tested Python module deterministically from the current
Git HEAD and ISO week, asks the authenticated local Gemini code-fix endpoint for
a minimal unified diff, records the result, and sends a proposal to General
Controller. It never applies a patch.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Sequence

import httpx

from development_control.security_guard import SecurityGuard
from storage.project_database import ProjectDatabase

REVIEW_PROMPT = (
    "Проверь модуль на типизацию, дублирование, сложность, обработку ошибок, "
    "документацию. Не меняй поведение, безопасность, торговые блокировки. "
    "Верни unified diff или NO_CHANGE."
)
EXCLUDED_PREFIXES = (".github/", "deploy/", "execution/", "risk_engine/")
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_DIFF_PATH = re.compile(r"^(?:---|\+\+\+) (?:a/|b/)?(.+)$")


@dataclass(frozen=True, slots=True)
class Candidate:
    module_path: str
    test_paths: tuple[str, ...]
    size_bytes: int


@dataclass(frozen=True, slots=True)
class ReviewOutcome:
    review_id: str
    module_path: str
    week_key: str
    head_sha: str
    status: str
    metadata_path: str
    patch_path: str = ""
    request_id: str = ""
    model: str = ""


class WeeklyCodeReviewer:
    """Build exactly one non-applying code-review proposal per HEAD/week/module."""

    def __init__(
        self,
        *,
        repo_root: str | Path | None = None,
        fixes_dir: str | Path | None = None,
        endpoint: str | None = None,
        service_token: str | None = None,
        timeout_seconds: float | None = None,
        max_module_bytes: int | None = None,
        database_factory: Callable[[], ProjectDatabase] = ProjectDatabase,
        http_client_factory: Callable[..., httpx.Client] = httpx.Client,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        self.repo_root = Path(
            repo_root or os.getenv("WEEKLY_CODE_REVIEW_REPO_DIR", "/workspace")
        ).resolve()
        data_dir = Path(os.getenv("SHARIPOVAI_DATA_DIR", "/var/lib/sharipovai"))
        self.fixes_dir = Path(
            fixes_dir
            or os.getenv(
                "WEEKLY_CODE_REVIEW_FIXES_DIR",
                str(data_dir / "agent_fixes"),
            )
        ).resolve()
        self.endpoint = endpoint or os.getenv(
            "SHARIPOVAI_CODE_FIX_ENDPOINT",
            "http://127.0.0.1:8000/internal/ai/code-fix",
        )
        self.service_token = service_token or os.getenv(
            "SHARIPOVAI_SERVICE_TOKEN", ""
        ).strip()
        self.timeout_seconds = float(
            timeout_seconds
            if timeout_seconds is not None
            else os.getenv("WEEKLY_CODE_REVIEW_TIMEOUT_SECONDS", "60")
        )
        self.max_module_bytes = int(
            max_module_bytes
            if max_module_bytes is not None
            else os.getenv("WEEKLY_CODE_REVIEW_MAX_MODULE_BYTES", "18000")
        )
        self.database_factory = database_factory
        self.http_client_factory = http_client_factory
        self.now_factory = now_factory or (lambda: datetime.now(UTC))
        self.guard = SecurityGuard()

    def run(self) -> ReviewOutcome:
        self._validate_configuration()
        head_sha = git_head_sha(self.repo_root)
        week_key = iso_week_key(self.now_factory())
        candidates = discover_candidates(
            self.repo_root,
            max_module_bytes=self.max_module_bytes,
        )
        if not candidates:
            raise RuntimeError(
                "No eligible tested Python modules found after exclusions"
            )
        candidate = choose_candidate(candidates, head_sha=head_sha, week_key=week_key)
        review_id = make_review_id(
            head_sha=head_sha,
            week_key=week_key,
            module_path=candidate.module_path,
        )
        metadata_path = self.fixes_dir / f"{review_id}.json"
        if metadata_path.is_file():
            record = _read_json(metadata_path)
            return ReviewOutcome(
                review_id=review_id,
                module_path=candidate.module_path,
                week_key=week_key,
                head_sha=head_sha,
                status=str(record.get("status", "already_recorded")),
                metadata_path=str(metadata_path),
                patch_path=str(record.get("patch_path", "")),
                request_id=str(record.get("request_id", "")),
                model=str(record.get("model", "")),
            )

        source_path = self.repo_root / candidate.module_path
        source = source_path.read_text(encoding="utf-8")
        request_message = build_request_message(
            prompt=REVIEW_PROMPT,
            module_path=candidate.module_path,
            source=source,
            head_sha=head_sha,
            week_key=week_key,
        )
        request_sha256 = hashlib.sha256(
            request_message.encode("utf-8")
        ).hexdigest()
        response = self._request_review(
            message=request_message,
            request_sha256=request_sha256,
        )
        raw_text = str(response.get("text", "")).strip()
        normalized = "NO_CHANGE" if not raw_text else raw_text

        status = "no_change"
        reasons: list[str] = []
        patch_path = ""
        patch_sha256 = ""
        if normalized != "NO_CHANGE":
            status, reasons = self._validate_patch(
                normalized,
                expected_module=candidate.module_path,
            )
            if status == "proposed":
                patch_file = self.fixes_dir / f"{review_id}.patch"
                _atomic_write_text(patch_file, normalized + "\n")
                patch_path = str(patch_file)
                patch_sha256 = hashlib.sha256(
                    normalized.encode("utf-8")
                ).hexdigest()

        generated_at = self.now_factory().astimezone(UTC).isoformat()
        record: dict[str, Any] = {
            "review_id": review_id,
            "kind": "code_review",
            "status": status,
            "module_path": candidate.module_path,
            "test_paths": list(candidate.test_paths),
            "head_sha": head_sha,
            "week_key": week_key,
            "prompt": REVIEW_PROMPT,
            "result": normalized if normalized == "NO_CHANGE" else "UNIFIED_DIFF",
            "patch_path": patch_path,
            "patch_sha256": patch_sha256,
            "validation_reasons": reasons,
            "request_sha256": request_sha256,
            "request_id": str(response.get("request_id", "")),
            "model": str(response.get("model", "")),
            "generated_at": generated_at,
            "auto_apply": False,
            "owner_approval_required": True,
        }
        self.fixes_dir.mkdir(parents=True, exist_ok=True)
        self._persist_and_propose(record)
        _atomic_write_json(metadata_path, record)

        return ReviewOutcome(
            review_id=review_id,
            module_path=candidate.module_path,
            week_key=week_key,
            head_sha=head_sha,
            status=status,
            metadata_path=str(metadata_path),
            patch_path=patch_path,
            request_id=record["request_id"],
            model=record["model"],
        )

    def _validate_configuration(self) -> None:
        if not self.repo_root.is_dir():
            raise RuntimeError(f"Repository not found: {self.repo_root}")
        if not self.service_token:
            raise RuntimeError("SHARIPOVAI_SERVICE_TOKEN is not configured")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.max_module_bytes < 1000:
            raise ValueError("max_module_bytes must be at least 1000")

    def _request_review(
        self,
        *,
        message: str,
        request_sha256: str,
    ) -> dict[str, Any]:
        payload = {
            "message": message,
            "history": [],
            "request_sha256": request_sha256,
        }
        headers = {
            "X-SharipovAI-Service-Token": self.service_token,
            "Accept": "application/json",
        }
        try:
            with self.http_client_factory(
                timeout=self.timeout_seconds,
                follow_redirects=False,
            ) as client:
                response = client.post(
                    self.endpoint,
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise RuntimeError(
                f"Weekly code review request failed: {type(exc).__name__}: {exc}"
            ) from exc
        if not isinstance(data, dict):
            raise RuntimeError("Internal code-fix response must be a JSON object")
        return data

    def _validate_patch(
        self,
        patch: str,
        *,
        expected_module: str,
    ) -> tuple[str, list[str]]:
        verdict = self.guard.check(patch)
        reasons = list(verdict.reasons)
        touched = changed_paths(patch)
        if not touched:
            reasons.append("unified diff does not contain changed paths")
        unexpected = sorted(path for path in touched if path != expected_module)
        if unexpected:
            reasons.append(
                "code review patch touches files outside selected module: "
                + ", ".join(unexpected)
            )
        if expected_module not in touched:
            reasons.append("selected module is not changed by the proposed patch")
        return ("blocked", reasons) if reasons else ("proposed", [])

    def _persist_and_propose(self, record: dict[str, Any]) -> None:
        database = self.database_factory()
        database.initialize()
        review_id = str(record["review_id"])
        database.put_json("agent_fixes", review_id, record)
        proposal = {
            "proposal_id": review_id,
            "kind": "code_review",
            "source": "weekly_code_reviewer",
            "module_path": record["module_path"],
            "head_sha": record["head_sha"],
            "week_key": record["week_key"],
            "review_status": record["status"],
            "patch_path": record["patch_path"],
            "patch_sha256": record["patch_sha256"],
            "validation_reasons": record["validation_reasons"],
            "auto_apply": False,
            "owner_approval_required": True,
            "decision": "OWNER_REVIEW_REQUIRED"
            if record["status"] == "proposed"
            else "NO_AUTOMATIC_CHANGE",
            "generated_at": record["generated_at"],
        }
        database.put_json("general_controller_proposals", review_id, proposal)
        existing = database.list_events(
            "general_controller",
            entity_type="proposal",
            entity_id=review_id,
            limit=1,
        )
        if not existing:
            database.append_event(
                "general_controller",
                "proposal",
                review_id,
                proposal,
                event_id=f"code-review-{review_id}",
            )


def iso_week_key(value: datetime) -> str:
    normalized = value.astimezone(UTC)
    iso_year, iso_week, _ = normalized.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def git_head_sha(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )
    sha = result.stdout.strip().lower()
    if result.returncode != 0 or not _SHA40.fullmatch(sha):
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"Cannot resolve repository HEAD: {detail}")
    return sha


def discover_candidates(
    repo_root: Path,
    *,
    max_module_bytes: int = 18000,
) -> list[Candidate]:
    paths = _tracked_python_paths(repo_root)
    test_paths = sorted(path for path in paths if _is_test_path(path))
    test_contents = {
        path: _safe_read(repo_root / path)
        for path in test_paths
    }
    candidates: list[Candidate] = []
    for path in sorted(paths):
        if _is_test_path(path) or _excluded(path):
            continue
        file_path = repo_root / path
        try:
            size = file_path.stat().st_size
        except OSError:
            continue
        if size <= 0 or size > max_module_bytes:
            continue
        related = tuple(
            test_path
            for test_path in test_paths
            if _test_covers_module(
                module_path=path,
                test_path=test_path,
                test_source=test_contents[test_path],
            )
        )
        if related:
            candidates.append(Candidate(path, related, size))
    return candidates


def choose_candidate(
    candidates: Sequence[Candidate],
    *,
    head_sha: str,
    week_key: str,
) -> Candidate:
    if not candidates:
        raise ValueError("candidates must not be empty")
    ordered = sorted(candidates, key=lambda item: item.module_path)
    digest = hashlib.sha256(f"{head_sha}:{week_key}".encode("utf-8")).digest()
    index = int.from_bytes(digest[:8], "big") % len(ordered)
    return ordered[index]


def make_review_id(*, head_sha: str, week_key: str, module_path: str) -> str:
    suffix = hashlib.sha256(
        f"{head_sha}:{week_key}:{module_path}".encode("utf-8")
    ).hexdigest()[:16]
    return f"code-review-{week_key.lower()}-{head_sha[:12]}-{suffix}"


def build_request_message(
    *,
    prompt: str,
    module_path: str,
    source: str,
    head_sha: str,
    week_key: str,
) -> str:
    return (
        f"{prompt}\n\n"
        f"Модуль: {module_path}\n"
        f"HEAD: {head_sha}\n"
        f"ISO-неделя: {week_key}\n\n"
        "Содержимое модуля:\n"
        "```python\n"
        f"{source}\n"
        "```"
    )


def changed_paths(patch: str) -> set[str]:
    paths: set[str] = set()
    for raw_line in patch.splitlines():
        match = _DIFF_PATH.match(raw_line)
        if not match:
            continue
        path = match.group(1).strip()
        if path == "/dev/null":
            continue
        normalized = _normalize_repo_path(path)
        if normalized:
            paths.add(normalized)
    return paths


def _tracked_python_paths(repo_root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z", "--", "*.py"],
        cwd=repo_root,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if result.returncode == 0:
        decoded = result.stdout.decode("utf-8", errors="strict")
        return sorted(
            _normalize_repo_path(item)
            for item in decoded.split("\0")
            if item
        )
    return sorted(
        path.relative_to(repo_root).as_posix()
        for path in repo_root.rglob("*.py")
        if ".git" not in path.parts
    )


def _is_test_path(path: str) -> bool:
    parts = Path(path).parts
    return (
        Path(path).name.startswith("test_")
        or "tests" in parts
        or "test" in parts
    )


def _excluded(path: str) -> bool:
    normalized = _normalize_repo_path(path)
    return any(normalized.startswith(prefix) for prefix in EXCLUDED_PREFIXES)


def _normalize_repo_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    return Path(normalized).as_posix()


def _test_covers_module(
    *,
    module_path: str,
    test_path: str,
    test_source: str,
) -> bool:
    module = Path(module_path)
    stem = module.stem
    dotted = module.with_suffix("").as_posix().replace("/", ".")
    test_name = Path(test_path).name
    if test_name in {f"test_{stem}.py", f"{stem}_test.py"}:
        return True
    patterns = (
        rf"(?m)^\s*import\s+{re.escape(dotted)}(?:\s|$|,)",
        rf"(?m)^\s*from\s+{re.escape(dotted)}\s+import\s+",
    )
    return any(re.search(pattern, test_source) for pattern in patterns)


def _safe_read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _atomic_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    _atomic_write_text(
        path,
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def _json_output(outcome: ReviewOutcome) -> str:
    return json.dumps(
        {
            "status": outcome.status,
            "review_id": outcome.review_id,
            "module_path": outcome.module_path,
            "week_key": outcome.week_key,
            "head_sha": outcome.head_sha,
            "metadata_path": outcome.metadata_path,
            "patch_path": outcome.patch_path,
            "request_id": outcome.request_id,
            "model": outcome.model,
            "auto_apply": False,
            "owner_approval_required": True,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create one owner-approved weekly code review proposal."
    )
    parser.add_argument("--repo-root")
    parser.add_argument("--fixes-dir")
    args = parser.parse_args(argv)
    try:
        outcome = WeeklyCodeReviewer(
            repo_root=args.repo_root,
            fixes_dir=args.fixes_dir,
        ).run()
    except Exception as exc:  # fail closed for the systemd service
        print(
            json.dumps(
                {
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                    "auto_apply": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    print(_json_output(outcome))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
