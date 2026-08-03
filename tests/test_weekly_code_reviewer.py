from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.weekly_code_reviewer import (
    Candidate,
    WeeklyCodeReviewer,
    choose_candidate,
    discover_candidates,
    iso_week_key,
)


class FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return dict(self.payload)


class FakeClient:
    def __init__(self, payload: dict[str, Any], calls: list[dict[str, Any]], **_: Any) -> None:
        self.payload = payload
        self.calls = calls

    def __enter__(self) -> "FakeClient":
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def post(self, url: str, *, headers: dict[str, str], json: dict[str, Any]) -> FakeResponse:
        self.calls.append({"url": url, "headers": headers, "json": json})
        return FakeResponse(self.payload)


class FakeDatabase:
    def __init__(self) -> None:
        self.initialized = False
        self.values: dict[tuple[str, str], dict[str, Any]] = {}
        self.events: list[dict[str, Any]] = []

    def initialize(self) -> None:
        self.initialized = True

    def put_json(self, namespace: str, key: str, value: dict[str, Any]) -> int:
        self.values[(namespace, key)] = dict(value)
        return 1

    def list_events(self, namespace: str, **filters: Any) -> list[dict[str, Any]]:
        return [
            event
            for event in self.events
            if event["namespace"] == namespace
            and event["entity_type"] == filters.get("entity_type")
            and event["entity_id"] == filters.get("entity_id")
        ]

    def append_event(
        self,
        namespace: str,
        entity_type: str,
        entity_id: str,
        payload: dict[str, Any],
        *,
        event_id: str,
    ) -> str:
        self.events.append(
            {
                "event_id": event_id,
                "namespace": namespace,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "payload": dict(payload),
            }
        )
        return event_id


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    files = {
        "pkg/alpha.py": "def value() -> int:\n    return 1\n",
        "tests/test_alpha.py": "from pkg.alpha import value\n\ndef test_value():\n    assert value() == 1\n",
        "pkg/orphan.py": "VALUE = 2\n",
        "deploy/ignored.py": "VALUE = 3\n",
        "tests/test_ignored.py": "from deploy.ignored import VALUE\n",
        "execution/ignored.py": "VALUE = 4\n",
        "risk_engine/ignored.py": "VALUE = 5\n",
        ".github/ignored.py": "VALUE = 6\n",
    }
    for relative, content in files.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "tests@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "SharipovAI Tests"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=repo, check=True)
    return repo


def _reviewer(
    repo: Path,
    fixes: Path,
    *,
    response_payload: dict[str, Any],
    calls: list[dict[str, Any]],
    database: FakeDatabase,
) -> WeeklyCodeReviewer:
    return WeeklyCodeReviewer(
        repo_root=repo,
        fixes_dir=fixes,
        endpoint="http://127.0.0.1:8000/internal/ai/code-fix",
        service_token="service-token",
        database_factory=lambda: database,
        http_client_factory=lambda **kwargs: FakeClient(response_payload, calls, **kwargs),
        now_factory=lambda: datetime(2026, 8, 4, 0, 0, tzinfo=UTC),
    )


def test_candidate_discovery_excludes_protected_and_untested_modules(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)

    candidates = discover_candidates(repo)

    assert [item.module_path for item in candidates] == ["pkg/alpha.py"]
    assert candidates[0].test_paths == ("tests/test_alpha.py",)


def test_selection_is_deterministic_for_head_and_iso_week() -> None:
    candidates = [
        Candidate("a.py", ("tests/test_a.py",), 10),
        Candidate("b.py", ("tests/test_b.py",), 10),
        Candidate("c.py", ("tests/test_c.py",), 10),
    ]
    head = "a" * 40

    first = choose_candidate(candidates, head_sha=head, week_key="2026-W32")
    second = choose_candidate(list(reversed(candidates)), head_sha=head, week_key="2026-W32")

    assert first == second
    assert iso_week_key(datetime(2026, 8, 4, tzinfo=UTC)) == "2026-W32"


def test_review_is_persisted_and_proposed_without_applying_patch(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    fixes = tmp_path / "agent_fixes"
    database = FakeDatabase()
    calls: list[dict[str, Any]] = []
    original = (repo / "pkg/alpha.py").read_text(encoding="utf-8")
    patch = """diff --git a/pkg/alpha.py b/pkg/alpha.py
--- a/pkg/alpha.py
+++ b/pkg/alpha.py
@@ -1,2 +1,3 @@
 def value() -> int:
+    \"\"\"Return the stable fixture value.\"\"\"
     return 1
"""

    outcome = _reviewer(
        repo,
        fixes,
        response_payload={"text": patch, "model": "gemini-test", "request_id": "fix-1"},
        calls=calls,
        database=database,
    ).run()

    assert outcome.status == "proposed"
    assert (repo / "pkg/alpha.py").read_text(encoding="utf-8") == original
    assert Path(outcome.patch_path).read_text(encoding="utf-8").startswith("diff --git")
    record = json.loads(Path(outcome.metadata_path).read_text(encoding="utf-8"))
    assert record["kind"] == "code_review"
    assert record["auto_apply"] is False
    assert record["owner_approval_required"] is True
    assert database.values[("agent_fixes", outcome.review_id)]["status"] == "proposed"
    proposal = database.values[("general_controller_proposals", outcome.review_id)]
    assert proposal["kind"] == "code_review"
    assert proposal["decision"] == "OWNER_REVIEW_REQUIRED"
    assert database.events[0]["namespace"] == "general_controller"
    assert calls[0]["headers"]["X-SharipovAI-Service-Token"] == "service-token"
    assert "Не меняй поведение, безопасность, торговые блокировки" in calls[0]["json"]["message"]


def test_no_change_is_recorded_and_same_week_is_idempotent(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    fixes = tmp_path / "agent_fixes"
    database = FakeDatabase()
    calls: list[dict[str, Any]] = []
    reviewer = _reviewer(
        repo,
        fixes,
        response_payload={"text": "", "model": "gemini-test", "request_id": "fix-2"},
        calls=calls,
        database=database,
    )

    first = reviewer.run()
    second = reviewer.run()

    assert first.status == "no_change"
    assert second.review_id == first.review_id
    assert first.patch_path == ""
    assert len(calls) == 1
    record = json.loads(Path(first.metadata_path).read_text(encoding="utf-8"))
    assert record["result"] == "NO_CHANGE"
    proposal = database.values[("general_controller_proposals", first.review_id)]
    assert proposal["decision"] == "NO_AUTOMATIC_CHANGE"


def test_patch_for_another_file_is_blocked_and_never_applied(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    fixes = tmp_path / "agent_fixes"
    database = FakeDatabase()
    calls: list[dict[str, Any]] = []
    original = (repo / "pkg/orphan.py").read_text(encoding="utf-8")
    patch = """diff --git a/pkg/orphan.py b/pkg/orphan.py
--- a/pkg/orphan.py
+++ b/pkg/orphan.py
@@ -1 +1 @@
-VALUE = 2
+VALUE: int = 2
"""

    outcome = _reviewer(
        repo,
        fixes,
        response_payload={"text": patch, "model": "gemini-test", "request_id": "fix-3"},
        calls=calls,
        database=database,
    ).run()

    assert outcome.status == "blocked"
    assert (repo / "pkg/orphan.py").read_text(encoding="utf-8") == original
    record = json.loads(Path(outcome.metadata_path).read_text(encoding="utf-8"))
    assert any("outside selected module" in reason for reason in record["validation_reasons"])
    assert record["auto_apply"] is False


def test_missing_service_token_fails_closed(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    reviewer = WeeklyCodeReviewer(
        repo_root=repo,
        fixes_dir=tmp_path / "agent_fixes",
        service_token="",
        database_factory=FakeDatabase,
    )

    try:
        reviewer.run()
    except RuntimeError as exc:
        assert "SHARIPOVAI_SERVICE_TOKEN" in str(exc)
    else:
        raise AssertionError("reviewer must fail closed without service token")
