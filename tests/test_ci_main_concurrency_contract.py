from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"

PUSH_AND_PR_WORKFLOWS = (
    "ci.yml",
    "tests.yml",
    "project-guardrails.yml",
    "secret-history-scan.yml",
)


def _concurrency_block(name: str) -> str:
    text = (WORKFLOWS / name).read_text(encoding="utf-8")
    block = text.split("concurrency:", 1)[1].split("\njobs:", 1)[0]
    return block


def test_main_push_verification_is_commit_scoped() -> None:
    for name in PUSH_AND_PR_WORKFLOWS:
        block = _concurrency_block(name)
        assert "github.sha" in block, name
        assert "github.ref" not in block, name


def test_pull_request_verification_still_supersedes_stale_pr_revisions() -> None:
    for name in PUSH_AND_PR_WORKFLOWS:
        block = _concurrency_block(name)
        assert "github.event.pull_request.number" in block, name
        assert "cancel-in-progress: true" in block, name
