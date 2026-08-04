"""CLI entrypoint for repeatable Docker-side patch verification."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from development_control.patch_policy import MAX_PATCH_BYTES
from development_control.security_guard import validate_patch


def _verify(path: Path, max_bytes: int) -> tuple[int, dict[str, object]]:
    try:
        stat = path.lstat()
        if path.is_symlink() or not path.is_file():
            raise ValueError("patch path must be a regular non-symlink file")
        if stat.st_size <= 0 or stat.st_size > max_bytes:
            raise ValueError(f"patch size must be 1..{max_bytes} bytes")
        patch = path.read_bytes()
    except (OSError, ValueError) as exc:
        return 1, {"allowed": False, "reasons": [f"patch read failed: {exc}"]}

    verdict = validate_patch(patch)
    return (0 if verdict.allowed else 2), {
        "allowed": verdict.allowed,
        "reasons": list(verdict.reasons),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify an approved SharipovAI unified diff")
    parser.add_argument("--verify", metavar="PATCH", type=Path, required=True)
    parser.add_argument("--max-bytes", type=int, default=MAX_PATCH_BYTES)
    args = parser.parse_args(argv)
    if args.max_bytes < 1:
        parser.error("--max-bytes must be positive")
    code, payload = _verify(args.verify, args.max_bytes)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
