"""Capture the proven production Compose identity without exporting its secrets."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,199}$")
PROJECT = re.compile(r"^[a-z0-9][a-z0-9_-]{0,199}$")
SHA = re.compile(r"^[0-9a-f]{40}$")
IMAGE = re.compile(r"^sha256:[0-9a-f]{64}$")
LOCKS = {
    "EXECUTION_KILL_SWITCH": "1",
    "EXCHANGE_LIVE_TRADING_ENABLED": "0",
    "FEATURE_BYBIT_LIVE_EXECUTION": "0",
    "TESTNET_EXECUTION_ENABLED": "0",
    "FEATURE_BYBIT_TESTNET": "0",
    "AUTONOMOUS_TESTNET_ENABLED": "0",
    "AUTONOMOUS_TESTNET_BRIDGE_ENABLED": "0",
    "EXCHANGE_MODE": "sandbox",
}


def runtime_context(app: dict[str, Any], proxy: dict[str, Any], image: dict[str, Any], expected_sha: str) -> dict[str, Any]:
    if not SHA.fullmatch(expected_sha):
        raise ValueError("expected revision must be a full SHA")
    if app.get("Name") != "/sharipovai" or app.get("State", {}).get("Status") != "running":
        raise ValueError("canonical application container is not running")
    if app.get("State", {}).get("Health", {}).get("Status") != "healthy":
        raise ValueError("canonical application Docker health is not healthy")
    if (proxy.get("Name") != "/sharipovai-caddy"
            or proxy.get("State", {}).get("Status") != "running"
            or (proxy.get("Config", {}).get("Labels") or {}).get("com.docker.compose.service") != "caddy"):
        raise ValueError("canonical Caddy container is not running or its identity is unproven")
    config = app.get("Config") or {}
    labels = config.get("Labels") or {}
    image_id = app.get("Image", "")
    if not IMAGE.fullmatch(image_id) or image.get("Id") != image_id:
        raise ValueError("running image identity is unproven")
    revision = (image.get("Config", {}).get("Labels") or {}).get("org.opencontainers.image.revision")
    env = dict(entry.split("=", 1) for entry in config.get("Env", []) if "=" in entry)
    if revision != expected_sha or env.get("SHARIPOVAI_BUILD_SHA") != expected_sha:
        raise ValueError("running image/build revision differs from checkout")
    for name, expected in LOCKS.items():
        if env.get(name) != expected:
            raise ValueError(f"production safety invariant failed: {name}")
    if labels.get("ai.sharipov.service") != "dashboard" or labels.get("ai.sharipov.runtime-mode") != "production-safe":
        raise ValueError("unexpected application identity")
    if labels.get("com.docker.compose.service") != "sharipovai":
        raise ValueError("unexpected Compose service")
    project = labels.get("com.docker.compose.project", "")
    if not PROJECT.fullmatch(project):
        raise ValueError("runtime Compose project is unavailable or unsafe")
    mounts = [m for m in app.get("Mounts", []) if m.get("Destination") == "/var/lib/sharipovai"]
    if len(mounts) != 1 or mounts[0].get("Type") != "volume" or not NAME.fullmatch(mounts[0].get("Name", "")):
        raise ValueError("canonical named data volume is unproven")
    shared = set(app.get("NetworkSettings", {}).get("Networks", {})) & set(proxy.get("NetworkSettings", {}).get("Networks", {}))
    if len(shared) != 1 or not NAME.fullmatch(next(iter(shared), "")):
        raise ValueError("one shared production proxy network is required")
    network = shared.pop()
    return {
        "project": project, "image_id": image_id, "revision": revision,
        "override": {
            "volumes": {"sharipovai_data": {"external": True, "name": mounts[0]["Name"]}},
            "networks": {"default": {"external": True, "name": network}},
        },
    }


def inspect(kind: str, target: str) -> dict[str, Any]:
    result = subprocess.run(["docker", kind, "inspect", target], capture_output=True, text=True, timeout=20)
    if result.returncode:
        raise RuntimeError(f"cannot inspect required {kind} identity")
    payload = json.loads(result.stdout)
    if not isinstance(payload, list) or len(payload) != 1:
        raise RuntimeError("ambiguous runtime identity")
    return payload[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        app = inspect("container", "sharipovai")
        context = runtime_context(app, inspect("container", "sharipovai-caddy"), inspect("image", app["Image"]), args.expected_sha)
        # The output is only names/structure. Never serialize Config.Env.
        # Refuse symlinks and set private permissions before writing any bytes.
        fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(json.dumps(context["override"], sort_keys=True))
        print(context["project"])
        return 0
    except (ValueError, RuntimeError, OSError, KeyError, TypeError, AttributeError, subprocess.TimeoutExpired) as error:
        print(f"runtime identity blocked: {error}", file=__import__("sys").stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
