from __future__ import annotations

import ipaddress
import sys
from pathlib import Path
from urllib.parse import urlsplit

PLACEHOLDER_HOSTS = {"sharipovai.example.com", "example.com"}
LOOPBACK_HOSTS = {"localhost", "localhost.localdomain"}


def normalize_https_target(raw: str) -> str:
    value = raw.strip().rstrip("{").strip()
    if not value:
        raise ValueError("public HTTPS target is empty")
    if "," in value or any(ch.isspace() for ch in value):
        raise ValueError("public HTTPS target must contain exactly one site address")
    if "://" not in value:
        value = f"https://{value}"

    parsed = urlsplit(value)
    if parsed.scheme.lower() != "https":
        raise ValueError("public HTTPS target must use https")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("public HTTPS target contains unsupported URL components")
    if parsed.path not in {"", "/"}:
        raise ValueError("public HTTPS target must not include a path")

    host = (parsed.hostname or "").strip().rstrip(".").lower()
    if not host:
        raise ValueError("public HTTPS target has no hostname")
    if host in LOOPBACK_HOSTS or host in PLACEHOLDER_HOSTS:
        raise ValueError(f"public HTTPS target is not public: {host}")

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        if "." not in host:
            raise ValueError("public HTTPS hostname must be fully qualified") from None
    else:
        if not ip.is_global:
            raise ValueError(f"public HTTPS target is not a global IP: {host}")

    authority = host if parsed.port is None else f"{host}:{parsed.port}"
    return f"https://{authority}"


def caddy_site(path: Path) -> str:
    if not path.is_file():
        raise ValueError(f"Caddyfile is missing: {path}")
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("{"):
            continue
        token = line.split("{", 1)[0].strip()
        if token:
            return token
    raise ValueError("Caddyfile contains no site address")


def resolve_public_base_url(override: str, caddyfile: Path) -> str:
    candidate = override.strip() if override.strip() else caddy_site(caddyfile)
    return normalize_https_target(candidate)


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: resolve_public_base_url.py <PUBLIC_BASE_URL> <Caddyfile>", file=sys.stderr)
        return 2
    try:
        print(resolve_public_base_url(argv[1], Path(argv[2])))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
