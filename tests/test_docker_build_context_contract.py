from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_nested_runtime_backups_are_excluded_from_docker_build_context() -> None:
    patterns = {
        line.strip()
        for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert "**/backups/" in patterns
    assert "**/emergency-recovery/" in patterns
