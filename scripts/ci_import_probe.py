"""Import the application and preserve a compact traceback for CI diagnosis."""
from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "ci-import-diagnostic.txt"


def main() -> int:
    os.chdir(ROOT)
    root_text = str(ROOT)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    try:
        import dashboard

        if dashboard.app is None:
            raise RuntimeError("dashboard.app is None")
        print("dashboard import: ok")
        OUTPUT.write_text("dashboard import: ok\n", encoding="utf-8")
        return 0
    except BaseException as exc:
        report = traceback.format_exc()
        OUTPUT.write_text(report, encoding="utf-8")
        print(f"IMPORT_ERROR: {type(exc).__name__}: {exc}")
        raise


if __name__ == "__main__":
    raise SystemExit(main())
