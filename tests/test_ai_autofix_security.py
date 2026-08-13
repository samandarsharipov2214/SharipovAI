from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

from development_control.security_guard import validate_patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ai_autofix.py"


def _load_autofix_module():
    spec = importlib.util.spec_from_file_location("ai_autofix_under_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _sandbox_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "sample.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo / "test_sample.py").write_text(
        "from sample import VALUE\n\n\ndef test_value():\n    assert VALUE == 2\n",
        encoding="utf-8",
    )
    _run_git(repo, "init")
    _run_git(repo, "config", "user.email", "tests@example.invalid")
    _run_git(repo, "config", "user.name", "Tests")
    _run_git(repo, "add", "sample.py", "test_sample.py")
    _run_git(repo, "commit", "-m", "initial")
    return repo


SAFE_PATCH = """diff --git a/sample.py b/sample.py
index a1b2c3d..d4e5f6a 100644
--- a/sample.py
+++ b/sample.py
@@ -1 +1 @@
-VALUE = 1
+VALUE = 2
"""


def test_allowed_patch_passes_security_guard_but_legacy_route_never_applies_it(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _sandbox_repo(tmp_path)
    autofix = _load_autofix_module()
    monkeypatch.setattr(autofix, "ROOT", repo)

    def no_git_mutation(*_args, **_kwargs):
        raise AssertionError("legacy autofix must not invoke git")

    monkeypatch.setattr(autofix, "run", no_git_mutation)

    assert validate_patch(SAFE_PATCH).allowed
    assert autofix.apply_patch(SAFE_PATCH) is False
    assert (repo / "sample.py").read_text(encoding="utf-8") == "VALUE = 1\n"


def test_protected_patch_is_blocked_before_git_apply(monkeypatch) -> None:
    autofix = _load_autofix_module()
    protected = SAFE_PATCH.replace("sample.py", "CONSTITUTION.md")

    def git_apply_must_not_run(*_args, **_kwargs):
        raise AssertionError("protected patch reached git")

    monkeypatch.setattr(autofix, "run", git_apply_must_not_run)
    assert autofix.apply_patch(protected) is False


def test_invalid_patch_fails_closed_before_git_apply(monkeypatch) -> None:
    autofix = _load_autofix_module()
    invalid = "diff --git a/sample.py b/sample.py\nthis is not a unified diff\n"

    def git_apply_must_not_run(*_args, **_kwargs):
        raise AssertionError("invalid patch reached git")

    monkeypatch.setattr(autofix, "run", git_apply_must_not_run)
    assert autofix.apply_patch(invalid) is False


def test_legacy_autofix_has_no_external_provider_or_direct_apply_route() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "api.openai.com" not in source
    assert "OPENAI_API_KEY" not in source
    assert '"git", "apply"' not in source
    assert "internal Gemini" in source
