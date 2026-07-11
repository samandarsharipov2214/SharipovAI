from __future__ import annotations

import io
import json

from scripts.production_smoke import run_smoke


class Response:
    def __init__(self, status: int, body: str):
        self.status = status
        self._body = io.BytesIO(body.encode("utf-8"))

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def getcode(self):
        return self.status

    def read(self, limit=-1):
        return self._body.read(limit)


def safe_health(**overrides):
    configuration = {
        "status": "ok",
        "kill_switch": True,
        "testnet_execution_enabled": False,
        "live_execution_enabled": False,
    }
    configuration.update(overrides.pop("configuration", {}))
    payload = {
        "status": "ok",
        "database": {"status": "ok"},
        "configuration": configuration,
    }
    payload.update(overrides)
    return payload


def opener_for(health, homepage="<html><title>SharipovAI</title></html>"):
    def opener(request, timeout):
        url = request.full_url
        if url.endswith("/health"):
            return Response(200, json.dumps(health))
        return Response(200, homepage)
    return opener


def test_production_smoke_accepts_only_safe_health_and_homepage() -> None:
    result = run_smoke(
        "https://sharipovai-bot.onrender.com",
        attempts=1,
        sleep_seconds=0,
        opener=opener_for(safe_health()),
    )
    assert result.status == "ok"
    assert result.errors == ()
    assert result.homepage_status == 200


def test_production_smoke_blocks_database_and_execution_failures() -> None:
    payload = safe_health(
        database={"status": "error"},
        configuration={
            "status": "error",
            "kill_switch": False,
            "testnet_execution_enabled": True,
            "live_execution_enabled": True,
        },
    )
    result = run_smoke(
        "https://example.com",
        attempts=1,
        sleep_seconds=0,
        opener=opener_for(payload),
    )
    assert result.status == "blocked"
    assert any("database" in item for item in result.errors)
    assert any("kill switch" in item for item in result.errors)
    assert any("Testnet" in item for item in result.errors)
    assert any("Live" in item for item in result.errors)


def test_production_smoke_retries_transient_failure() -> None:
    calls = {"health": 0}

    def opener(request, timeout):
        if request.full_url.endswith("/health"):
            calls["health"] += 1
            if calls["health"] == 1:
                raise TimeoutError("cold start")
            return Response(200, json.dumps(safe_health()))
        return Response(200, "SharipovAI")

    result = run_smoke(
        "https://example.com",
        attempts=2,
        sleep_seconds=0,
        opener=opener,
    )
    assert result.status == "ok"
    assert result.attempts == 2


def test_production_smoke_blocks_wrong_homepage_identity() -> None:
    result = run_smoke(
        "https://example.com",
        attempts=1,
        sleep_seconds=0,
        opener=opener_for(safe_health(), homepage="<html>Unknown service</html>"),
    )
    assert result.status == "blocked"
    assert "SharipovAI identity" in result.errors[-1]
