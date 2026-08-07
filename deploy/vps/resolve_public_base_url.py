from pathlib import Path


def caddy_site(path: Path) -> str:
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and not line.startswith("{"):
            return line.split("{", 1)[0].strip()
    raise ValueError("no Caddy site address")
