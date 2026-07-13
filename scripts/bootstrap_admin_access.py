"""Create or reset one persistent SharipovAI administrator account.

The script is intended to be streamed into the running container. It writes only
the users database in SHARIPOVAI_DATA_DIR and prints a one-time temporary
password which must be changed after the first login.
"""
from __future__ import annotations

import json
import os
import secrets
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path("/app")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dashboard.user_admin import hash_password


def _clean(username: str) -> str:
    return username.strip().lower().replace(" ", "_")


def _load(path: Path) -> tuple[dict[str, Any], bool]:
    if not path.exists():
        return {}, False
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        raw = {}
    if isinstance(raw, dict) and isinstance(raw.get("users"), dict):
        return dict(raw), True
    return (raw if isinstance(raw, dict) else {}), False


def _save(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def main() -> int:
    username = _clean(sys.argv[1] if len(sys.argv) > 1 else "samandar")
    if not username:
        raise SystemExit("username is empty")

    data_dir = Path(os.getenv("SHARIPOVAI_DATA_DIR", "/var/lib/sharipovai"))
    users_path = Path(os.getenv("SHARIPOVAI_USERS_FILE", str(data_dir / "users.json")))
    payload, wrapped = _load(users_path)
    users = payload.setdefault("users", {}) if wrapped else payload

    temporary_password = f"SA-{secrets.token_urlsafe(12)}"
    previous = users.get(username) if isinstance(users.get(username), dict) else {}
    users[username] = {
        **previous,
        "password_hash": hash_password(temporary_password),
        "active": True,
        "role": "admin",
        "must_change_password": True,
        "created_at": int(previous.get("created_at", 0) or time.time()),
        "password_reset_at": int(time.time()),
    }
    _save(users_path, payload)

    print(json.dumps({
        "status": "ok",
        "username": username,
        "temporary_password": temporary_password,
        "must_change_password": True,
        "users_file": str(users_path),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
