#!/usr/bin/env python3
"""Launch Self-Healing against a trusted alternate Git metadata snapshot.

The production worktree is bind-mounted read-only at /workspace while the real
host .git directory intentionally remains protected. The host supervisor creates
a sanitized Git metadata snapshot in the private runtime volume and points Git
at it through GIT_DIR/GIT_WORK_TREE. This runner also prevents temporary pytest
snapshots from traversing the protected host .git directory.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import self_healing_agent as agent  # noqa: E402


def _trusted_copy_repository_snapshot(source: Path, destination: Path) -> None:
    """Copy source for tests without traversing host Git metadata or secrets."""

    def ignore(directory: str, names: list[str]) -> set[str]:
        directory_path = Path(directory)
        try:
            relative = directory_path.relative_to(source).as_posix()
        except ValueError:
            relative = ""

        ignored = {
            name
            for name in names
            if name in agent.RUNTIME_IGNORES
            or name.startswith(".env")
            or name.endswith((".pem", ".key", ".p12", ".pfx"))
        }
        if relative in {"", "."}:
            # The active Git repository is supplied through GIT_DIR. Reading
            # source/.git would defeat the host permission boundary we are
            # explicitly preserving.
            ignored.add(".git")
        if relative == "deploy/vps":
            ignored.update(
                name
                for name in names
                if name in {"backups", "emergency-recovery"}
                or name.startswith("docker-compose.yml.bak-")
                or name.startswith(".env")
            )
        ignored.update(
            name
            for name in names
            if name.endswith(
                (
                    ".db",
                    ".db-wal",
                    ".db-shm",
                    ".sqlite",
                    ".sqlite3",
                    ".log",
                    ".pyc",
                )
            )
        )
        return ignored

    shutil.copytree(source, destination, ignore=ignore, symlinks=False)


def install_trusted_git_snapshot() -> None:
    git_dir_text = os.getenv("GIT_DIR", "").strip()
    work_tree_text = os.getenv("GIT_WORK_TREE", "").strip()
    repo_dir_text = os.getenv("SELF_HEALING_REPO_DIR", "/workspace").strip()

    if not git_dir_text or not work_tree_text:
        raise RuntimeError("trusted Git snapshot environment is incomplete")

    git_dir = Path(git_dir_text)
    work_tree = Path(work_tree_text)
    repo_dir = Path(repo_dir_text)
    if not git_dir.is_dir() or not (git_dir / "HEAD").is_file():
        raise RuntimeError(f"trusted Git snapshot is unavailable at {git_dir}")
    if work_tree.resolve() != repo_dir.resolve():
        raise RuntimeError(
            f"trusted Git worktree mismatch: GIT_WORK_TREE={work_tree} repo={repo_dir}"
        )

    # Keep the original agent implementation unchanged for all other callers.
    # Only this production runner swaps the temporary source copier so the
    # protected host .git tree is never traversed during related-test snapshots.
    agent.copy_repository_snapshot = _trusted_copy_repository_snapshot


def main(argv: list[str] | None = None) -> int:
    try:
        install_trusted_git_snapshot()
    except Exception as exc:  # noqa: BLE001 - fail closed before recovery logic
        print(
            f"Self-Healing trusted Git snapshot unavailable: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return agent.EXIT_UNRESOLVED
    return agent.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
