"""Read-only crypto knowledge readiness audit for the nine canonical organs."""
from __future__ import annotations

import json

from learning.crypto_knowledge_readiness import readiness_snapshot


def main() -> int:
    snapshot = readiness_snapshot()
    print(json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True))
    print(
        f"CRYPTO_KNOWLEDGE={snapshot['ready_organs']}/{snapshot['total_organs']} "
        f"status={snapshot['status']} execution_authority=false"
    )
    return 0 if snapshot["status"] == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
