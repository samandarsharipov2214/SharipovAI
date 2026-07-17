"""Structured JSON logging with bounded context and secret redaction."""
from __future__ import annotations

import json
import logging
import os
import re
import sys
from datetime import UTC, datetime
from typing import Any, Mapping

_SECRET_KEYS = {
    "authorization", "api_key", "api_secret", "secret", "token",
    "password", "cookie", "set-cookie",
}
_SECRET_PATTERN = re.compile(
    r"(?i)(api[_-]?key|api[_-]?secret|authorization|password|token|cookie)"
)


class ContextLoggerAdapter(logging.LoggerAdapter):
    def process(self, msg: Any, kwargs: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
        supplied = dict(kwargs.get("extra") or {})
        base = dict(self.extra or {})
        context = {
            **dict(base.get("context") or {}),
            **dict(supplied.get("context") or {}),
        }
        kwargs["extra"] = {**base, **supplied, "context": context}
        return msg, kwargs


class JsonFormatter(logging.Formatter):
    """Emit one stable JSON object per log record."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for name in (
            "event", "request_id", "method", "path", "status_code",
            "duration_ms", "candidate_id", "order_link_id", "symbol",
            "environment", "window_index", "dataset_id",
        ):
            value = getattr(record, name, None)
            if value not in (None, ""):
                payload[name] = _safe_value(name, value)
        context = getattr(record, "context", None)
        if isinstance(context, Mapping):
            payload["context"] = {
                str(key): _safe_value(str(key), value)
                for key, value in context.items()
            }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )


def configure_structured_logging(
    *,
    level: str | int | None = None,
    stream: Any = None,
) -> None:
    """Configure the root logger once without duplicating handlers."""

    root = logging.getLogger()
    for handler in root.handlers:
        if getattr(handler, "_sharipovai_json_handler", False):
            return
    configured_level: str | int = (
        level if level is not None else os.getenv("LOG_LEVEL", "INFO").upper()
    )
    handler = logging.StreamHandler(stream or sys.stdout)
    handler._sharipovai_json_handler = True  # type: ignore[attr-defined]
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(configured_level)


def get_structured_logger(name: str, **context: Any) -> ContextLoggerAdapter:
    configure_structured_logging()
    safe_context = {
        str(key): _safe_value(str(key), value)
        for key, value in context.items()
    }
    return ContextLoggerAdapter(
        logging.getLogger(name),
        {"context": safe_context},
    )


def log_event(
    logger: logging.Logger | logging.LoggerAdapter,
    level: int,
    message: str,
    *,
    event: str,
    context: Mapping[str, Any] | None = None,
    **fields: Any,
) -> None:
    extra = {
        "event": event,
        "context": {
            str(key): _safe_value(str(key), value)
            for key, value in dict(context or {}).items()
        },
    }
    for key, value in fields.items():
        extra[str(key)] = _safe_value(str(key), value)
    logger.log(level, message, extra=extra)


def _safe_value(name: str, value: Any) -> Any:
    normalized = name.strip().lower()
    if normalized in _SECRET_KEYS or _SECRET_PATTERN.search(normalized):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {
            str(key): _safe_value(str(key), item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_safe_value(name, item) for item in value]
    if isinstance(value, str) and len(value) > 2_000:
        return value[:2_000] + "...[truncated]"
    return value


__all__ = [
    "ContextLoggerAdapter",
    "JsonFormatter",
    "configure_structured_logging",
    "get_structured_logger",
    "log_event",
]
