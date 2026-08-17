#!/usr/bin/env python3
"""Launch Self-Healing against a trusted alternate Git metadata snapshot.

The production worktree is bind-mounted read-only at /workspace while the real
host .git directory intentionally remains protected. The host supervisor creates
a sanitized Git metadata snapshot in the private runtime volume and points Git
at it through GIT_DIR/GIT_WORK_TREE.

Temporary pytest snapshots are materialized from the trusted Git object/index
baseline and then overlay only real worktree content changes identified by the
trusted host supervisor. This avoids traversing unrelated production files whose
host permissions intentionally make them unreadable to the unprivileged
Self-Healing UID.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import self_healing_agent as agent  # noqa: E402

_SECRET_SUFFIXES = (".pem", ".key", ".p12", ".pfx")
_RUNTIME_SUFFIXES = (".db", ".db-wal", ".db-shm", ".sqlite", ".sqlite3", ".log", ".pyc")
_RUNTIME_PREFIXES = (
    "deploy/vps/backups/",
    "deploy/vps/emergency-recovery/",
)
_DEFAULT_CHANGED_PATHS_FILE = Path(
    "/var/lib/sharipovai/.self_healing/git-worktree-changes"
)


def _trusted_git_dir() -> Path:
    git_dir_text = os.getenv("GIT_DIR", "").strip()
    if not git_dir_text:
        raise RuntimeError("trusted Git snapshot environment is incomplete")
    git_dir = Path(git_dir_text)
    if not git_dir.is_dir() or not (git_dir / "HEAD").is_file() or not (git_dir / "index").is_file():
        raise RuntimeError(f"trusted Git snapshot is unavailable at {git_dir}")
    return git_dir


def _git_environment(*, git_dir: Path, work_tree: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "GIT_DIR": str(git_dir),
            "GIT_WORK_TREE": str(work_tree),
            "GIT_OPTIONAL_LOCKS": "0",
        }
    )
    return env


def _git_lines(*, git_dir: Path, work_tree: Path, args: tuple[str, ...]) -> tuple[str, ...]:
    result = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={work_tree}",
            "-c",
            "core.filemode=false",
            *args,
        ],
        cwd=work_tree,
        env=_git_environment(git_dir=git_dir, work_tree=work_tree),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "git command failed").strip()
        raise RuntimeError(f"trusted worktree Git inspection failed: {detail[-1200:]}")
    return tuple(line.strip() for line in result.stdout.splitlines() if line.strip())


def _overlay_allowed(relative: str) -> bool:
    clean = relative.replace("\\", "/")
    while clean.startswith("./"):
        clean = clean[2:]
    if not clean or clean.startswith("/") or clean == ".git" or clean.startswith(".git/"):
        return False
    if clean.startswith(_RUNTIME_PREFIXES):
        return False
    name = Path(clean).name
    if name in agent.RUNTIME_IGNORES or name.startswith(".env"):
        return False
    if clean.startswith("deploy/vps/docker-compose.yml.bak-"):
        return False
    if name.endswith(_SECRET_SUFFIXES) or name.endswith(_RUNTIME_SUFFIXES):
        return False
    return True


def _safe_destination(root: Path, relative: str) -> Path:
    candidate = root / relative
    resolved_root = root.resolve()
    resolved_parent = candidate.parent.resolve(strict=False)
    try:
        resolved_parent.relative_to(resolved_root)
    except ValueError as exc:
        raise RuntimeError(f"unsafe changed path outside snapshot: {relative}") from exc
    return candidate


def _materialize_trusted_head(*, trusted_git: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    destination_git = destination / ".git"
    shutil.copytree(trusted_git, destination_git, symlinks=False)

    result = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={destination}",
            "-c",
            "core.filemode=false",
            "checkout-index",
            "-a",
            "-f",
        ],
        cwd=destination,
        env=_git_environment(git_dir=destination_git, work_tree=destination),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "checkout-index failed").strip()
        raise RuntimeError(f"trusted Git HEAD materialization failed: {detail[-1200:]}")


def _changed_paths_manifest() -> Path | None:
    configured = os.getenv("SELF_HEALING_CHANGED_PATHS_FILE", "").strip()
    if configured:
        return Path(configured)
    return _DEFAULT_CHANGED_PATHS_FILE if _DEFAULT_CHANGED_PATHS_FILE.is_file() else None


def _manifest_lines(path: Path) -> tuple[str, ...]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"trusted host worktree change manifest is unreadable: {path}") from exc
    values: list[str] = []
    for raw in text.splitlines():
        relative = raw.strip()
        if not relative:
            continue
        if "\x00" in relative or relative.startswith("/"):
            raise RuntimeError(f"unsafe path in trusted host worktree change manifest: {relative!r}")
        values.append(relative)
    return tuple(values)


def _worktree_overlays(*, trusted_git: Path, source: Path) -> tuple[str, ...]:
    manifest = _changed_paths_manifest()
    if manifest is not None:
        changed = set(_manifest_lines(manifest))
    else:
        # Test/development fallback. Production always supplies the host-created
        # manifest because container permission differences can make an
        # unchanged unreadable tracked file look modified to container Git.
        changed = set(
            _git_lines(
                git_dir=trusted_git,
                work_tree=source,
                args=("diff", "--name-only", "--no-ext-diff"),
            )
        )
        changed.update(
            _git_lines(
                git_dir=trusted_git,
                work_tree=source,
                args=("ls-files", "--others", "--exclude-standard"),
            )
        )
    return tuple(sorted(path for path in changed if _overlay_allowed(path)))


def _overlay_changed_worktree(*, trusted_git: Path, source: Path, destination: Path) -> None:
    source_root = source.resolve()
    for relative in _worktree_overlays(trusted_git=trusted_git, source=source):
        source_path = source / relative
        destination_path = _safe_destination(destination, relative)

        # A tracked deletion must also be represented in the test snapshot.
        if not source_path.exists() and not source_path.is_symlink():
            if destination_path.is_dir() and not destination_path.is_symlink():
                shutil.rmtree(destination_path)
            else:
                destination_path.unlink(missing_ok=True)
            continue

        try:
            resolved_source = source_path.resolve(strict=True)
            resolved_source.relative_to(source_root)
        except (FileNotFoundError, ValueError) as exc:
            raise RuntimeError(f"unsafe changed worktree path: {relative}") from exc

        if source_path.is_symlink():
            raise RuntimeError(f"changed worktree symlink requires manual verification: {relative}")
        if not source_path.is_file():
            raise RuntimeError(f"changed worktree path is not a regular file: {relative}")

        destination_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with source_path.open("rb") as source_handle, destination_path.open("wb") as destination_handle:
                shutil.copyfileobj(source_handle, destination_handle)
        except PermissionError as exc:
            raise RuntimeError(
                f"changed worktree file is unreadable to Self-Healing and cannot be verified safely: {relative}"
            ) from exc

        source_mode = source_path.stat().st_mode
        destination_path.chmod(0o700 if source_mode & 0o111 else 0o600)


def _trusted_copy_repository_snapshot(source: Path, destination: Path) -> None:
    """Create a test snapshot without recursively reading the production tree."""

    trusted_git = _trusted_git_dir().resolve()
    source_resolved = source.resolve()
    try:
        trusted_git.relative_to(source_resolved)
    except ValueError:
        pass
    else:
        raise RuntimeError("trusted Git snapshot must be outside the protected worktree")

    _materialize_trusted_head(trusted_git=trusted_git, destination=destination)
    _overlay_changed_worktree(
        trusted_git=trusted_git,
        source=source,
        destination=destination,
    )


def install_trusted_git_snapshot() -> None:
    git_dir = _trusted_git_dir()
    work_tree_text = os.getenv("GIT_WORK_TREE", "").strip()
    repo_dir_text = os.getenv("SELF_HEALING_REPO_DIR", "/workspace").strip()

    if not work_tree_text:
        raise RuntimeError("trusted Git snapshot environment is incomplete")

    work_tree = Path(work_tree_text)
    repo_dir = Path(repo_dir_text)
    if work_tree.resolve() != repo_dir.resolve():
        raise RuntimeError(
            f"trusted Git worktree mismatch: GIT_WORK_TREE={work_tree} repo={repo_dir}"
        )
    try:
        git_dir.resolve().relative_to(repo_dir.resolve())
    except ValueError:
        pass
    else:
        raise RuntimeError("trusted Git snapshot must be outside the protected worktree")

    # Keep the original agent implementation unchanged for all other callers.
    # Only this production runner swaps the temporary source copier so the
    # protected host .git tree and unrelated unreadable files are never traversed.
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
