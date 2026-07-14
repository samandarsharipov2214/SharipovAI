"""Default-off read-only Bybit private order WebSocket worker.

The worker authenticates and subscribes only to the private ``order`` topic. It
has no order create/amend/cancel methods and delegates every event to the
fail-closed database-backed order state store. Runtime readiness and heartbeat
are persisted so Testnet startup can require factual private-stream evidence.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlsplit

from .bybit_credentials import private_stream_credentials
from .bybit_order_state import BybitOrderStateStore
from .private_ws_gate import PrivateStreamHealthRepository

_TESTNET_URL = "wss://stream-testnet.bybit.com/v5/private"
_MAINNET_URL = "wss://stream.bybit.com/v5/private"
_TESTNET_HOSTS = frozenset({"stream-testnet.bybit.com"})
_MAINNET_HOSTS = frozenset({"stream.bybit.com", "stream.bybit.eu"})
_AUTH_REQUEST_ID = "sharipovai-private-auth"
_SUBSCRIBE_REQUEST_ID = "sharipovai-private-orders"
_TRUE = {"1", "true", "yes", "on"}


def normalize_private_environment(value: Any) -> str:
    clean = str(value).strip().lower()
    if clean in {"sandbox", "testnet"}:
        return "testnet"
    if clean in {"live", "mainnet", "live_read_only"}:
        return "mainnet"
    raise ValueError("private WebSocket environment must be testnet or mainnet")


def validate_private_ws_url(value: Any, *, environment: str) -> str:
    normalized_environment = normalize_private_environment(environment)
    parsed = urlsplit(str(value or "").strip())
    host = (parsed.hostname or "").lower()
    if parsed.scheme.lower() != "wss":
        raise ValueError("Bybit private WebSocket URL must use wss")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Bybit private WebSocket URL must not contain userinfo")
    if parsed.port not in (None, 443):
        raise ValueError("Bybit private WebSocket URL must not use a custom port")
    allowed = _TESTNET_HOSTS if normalized_environment == "testnet" else _MAINNET_HOSTS
    if host not in allowed:
        raise ValueError("Bybit private WebSocket host is not approved for this environment")
    if parsed.path.rstrip("/") != "/v5/private" or parsed.query or parsed.fragment:
        raise ValueError("Bybit private WebSocket URL must target /v5/private")
    return f"wss://{host}/v5/private"


class BybitPrivateOrderWebSocket:
    """Consume authenticated order events without any trading capability."""

    def __init__(
        self,
        *,
        store: BybitOrderStateStore | None = None,
        health_repository: PrivateStreamHealthRepository | None = None,
        connector: Callable[..., Any] | None = None,
        clock_ms: Callable[[], int] | None = None,
        wait: Callable[[float], bool] | None = None,
    ) -> None:
        self.environment = normalize_private_environment(os.getenv("EXCHANGE_MODE", "sandbox"))
        default_url = _TESTNET_URL if self.environment == "testnet" else _MAINNET_URL
        self.url = validate_private_ws_url(
            os.getenv("BYBIT_PRIVATE_WS_URL", default_url),
            environment=self.environment,
        )
        credentials = private_stream_credentials(self.environment)
        self.api_key = credentials.api_key
        self.api_secret = credentials.api_secret
        self.credential_profile = credentials.profile
        self.store = store or BybitOrderStateStore(environment=self.environment)
        self.health_repository = health_repository or PrivateStreamHealthRepository(
            database=getattr(self.store, "database", None),
            environment=self.environment,
        )
        self.receive_timeout = _bounded_float(
            "BYBIT_PRIVATE_WS_RECEIVE_TIMEOUT_SECONDS", 15.0, 1.0, 60.0
        )
        self.auth_window_ms = int(
            _bounded_float("BYBIT_PRIVATE_WS_AUTH_WINDOW_SECONDS", 10.0, 5.0, 30.0)
            * 1000
        )
        self._connector = connector
        self._clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        self._stop = threading.Event()
        self._wait = wait or self._stop.wait
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._connected = False
        self._authenticated = False
        self._subscribed = False
        self._last_error = ""
        self._last_message_at_ms = 0
        self._last_heartbeat_at_ms = 0
        self._ready_at_ms = 0
        self._reconnect_attempt = 0
        self._publish_health()

    def enabled(self) -> bool:
        return os.getenv("FEATURE_BYBIT_PRIVATE_ORDER_WS", "0").strip().lower() in _TRUE

    def start(self) -> None:
        if not self.enabled():
            self._publish_health()
            return
        if not self.api_key or not self.api_secret:
            self._mark_disconnected("private WebSocket credentials are not configured")
            return
        if self._thread and self._thread.is_alive():
            self._publish_health()
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="bybit-private-order-websocket",
            daemon=True,
        )
        self._thread.start()
        self._publish_health()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=3.0)
        self._mark_disconnected("worker stopped")

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": self.enabled(),
                "worker_running": bool(self._thread and self._thread.is_alive()),
                "environment": self.environment,
                "url": self.url,
                "credential_profile": self.credential_profile,
                "credentials_configured": bool(self.api_key and self.api_secret),
                "connected": self._connected,
                "authenticated": self._authenticated,
                "subscribed": self._subscribed,
                "ready_at_ms": self._ready_at_ms,
                "last_message_at_ms": self._last_message_at_ms,
                "last_heartbeat_at_ms": self._last_heartbeat_at_ms,
                "last_error": self._last_error,
                "reconnect_attempt": self._reconnect_attempt,
            }

    def snapshot(self) -> dict[str, Any]:
        status = self.status()
        gate = self.health_repository.evaluate(
            required=self.enabled(),
            now_ms=self._clock_ms(),
            maximum_heartbeat_age_seconds=max(self.receive_timeout * 2.5, 30.0),
        )
        return {
            "status": "ok" if gate.ready else "unverified",
            "stream": status,
            "gate": gate.to_dict(),
            "order_state": self.store.snapshot(),
        }

    def reconcile(self, journal: Mapping[str, Any] | list[Any]) -> dict[str, Any]:
        result = self.store.reconcile(journal)
        gate = self.health_repository.evaluate(
            required=self.enabled(),
            now_ms=self._clock_ms(),
            maximum_heartbeat_age_seconds=max(self.receive_timeout * 2.5, 30.0),
        )
        if not gate.ready:
            result = {
                **result,
                "status": "blocked",
                "restart_safe": False,
                "errors": [*result["errors"], *gate.failed_gates],
                "private_stream_gate": gate.to_dict(),
            }
        else:
            result = {**result, "private_stream_gate": gate.to_dict()}
        return result

    def run_cycle(self) -> None:
        if not self.api_key or not self.api_secret:
            raise RuntimeError("private WebSocket credentials are not configured")
        try:
            with self._connect() as connection:
                self._consume_connection(connection)
        except Exception as exc:
            self._mark_disconnected(f"{type(exc).__name__}: {exc}")
            raise
        finally:
            if not self._stop.is_set():
                self._mark_disconnected("connection closed")

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.run_cycle()
            except Exception:
                with self._lock:
                    self._reconnect_attempt += 1
                    attempt = self._reconnect_attempt
                self._publish_health()
                if self._wait(float(min(2 ** min(attempt - 1, 5), 30))):
                    break

    def _connect(self) -> Any:
        connector = self._connector
        if connector is None:
            from websockets.sync.client import connect

            connector = connect
        return connector(
            self.url,
            open_timeout=10,
            close_timeout=3,
            ping_interval=20,
            ping_timeout=10,
            max_size=2_000_000,
        )

    def _consume_connection(self, connection: Any) -> None:
        expires = self._clock_ms() + self.auth_window_ms
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            f"GET/realtime{expires}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        connection.send(
            json.dumps(
                {
                    "req_id": _AUTH_REQUEST_ID,
                    "op": "auth",
                    "args": [self.api_key, expires, signature],
                },
                separators=(",", ":"),
            )
        )
        _validate_auth_ack(_decode(connection.recv(timeout=self.receive_timeout)))
        with self._lock:
            self._authenticated = True
        connection.send(
            json.dumps(
                {
                    "req_id": _SUBSCRIBE_REQUEST_ID,
                    "op": "subscribe",
                    "args": ["order"],
                },
                separators=(",", ":"),
            )
        )
        _validate_subscribe_ack(_decode(connection.recv(timeout=self.receive_timeout)))
        ready_at = self._clock_ms()
        with self._lock:
            self._connected = True
            self._subscribed = True
            self._ready_at_ms = ready_at
            self._last_heartbeat_at_ms = ready_at
            self._last_error = ""
            self._reconnect_attempt = 0
        self._publish_health(recorded_at_ms=ready_at)
        while not self._stop.is_set():
            payload = _decode(connection.recv(timeout=self.receive_timeout))
            received = self._clock_ms()
            op = str(payload.get("op", ""))
            if op in {"ping", "pong"} or payload.get("ret_msg") == "pong":
                with self._lock:
                    self._last_heartbeat_at_ms = received
                self._publish_health(recorded_at_ms=received)
                continue
            if op in {"auth", "subscribe"}:
                raise RuntimeError("unexpected duplicate private WebSocket control response")
            topic = str(payload.get("topic", ""))
            if topic != "order" and not topic.startswith("order."):
                raise RuntimeError(
                    f"unexpected private WebSocket topic: {topic or 'missing'}"
                )
            self.store.ingest_message(payload, received_at_ms=received)
            with self._lock:
                self._last_message_at_ms = received
                self._last_heartbeat_at_ms = received
            self._publish_health(recorded_at_ms=received)

    def _mark_disconnected(self, error: str) -> None:
        with self._lock:
            self._connected = False
            self._authenticated = False
            self._subscribed = False
            self._last_error = str(error)[:500]
        self._publish_health()

    def _publish_health(self, *, recorded_at_ms: int | None = None) -> None:
        try:
            self.health_repository.record(
                self.status(),
                recorded_at_ms=recorded_at_ms or self._clock_ms(),
            )
        except Exception:
            # Observability persistence must never create a second worker crash.
            pass


def _decode(raw: Any) -> dict[str, Any]:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    if not isinstance(raw, str):
        raise ValueError("Bybit private WebSocket message must be text")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("Bybit private WebSocket message must be an object")
    return payload


def _validate_auth_ack(payload: Mapping[str, Any]) -> None:
    if payload.get("op") != "auth" or payload.get("success") is not True:
        raise RuntimeError(
            f"Bybit private WebSocket authentication rejected: "
            f"{payload.get('ret_msg') or 'invalid ack'}"
        )
    if payload.get("req_id") not in (None, "", _AUTH_REQUEST_ID):
        raise RuntimeError("Bybit authentication ack has unexpected req_id")
    if str(payload.get("ret_msg", "")) not in {"", "OK"}:
        raise RuntimeError(
            f"Bybit authentication rejected: {payload.get('ret_msg')}"
        )


def _validate_subscribe_ack(payload: Mapping[str, Any]) -> None:
    if payload.get("op") != "subscribe" or payload.get("success") is not True:
        raise RuntimeError(
            f"Bybit private order subscription rejected: "
            f"{payload.get('ret_msg') or 'invalid ack'}"
        )
    if payload.get("req_id") not in (None, "", _SUBSCRIBE_REQUEST_ID):
        raise RuntimeError("Bybit subscription ack has unexpected req_id")
    data = payload.get("data")
    if isinstance(data, Mapping):
        failed = [str(item) for item in (data.get("failTopics") or [])]
        succeeded = {str(item) for item in (data.get("successTopics") or [])}
        if failed:
            raise RuntimeError(
                f"Bybit private order subscription failed: {', '.join(failed)}"
            )
        if succeeded and "order" not in succeeded:
            raise RuntimeError("Bybit subscription ack is missing order topic")


def _bounded_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    if not math.isfinite(value):
        return default
    return min(max(value, minimum), maximum)


__all__ = [
    "BybitPrivateOrderWebSocket",
    "normalize_private_environment",
    "validate_private_ws_url",
]
