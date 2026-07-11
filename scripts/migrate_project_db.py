"""Initialize or migrate the canonical SharipovAI database."""
from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from storage import ProjectDatabase


def main() -> int:
    database = ProjectDatabase()
    database.initialize()
    status = database.health()
    print(json.dumps(status, ensure_ascii=False, sort_keys=True))
    return 0 if status.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
