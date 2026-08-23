"""Secure Telegram deployment requests for the SharipovAI host watcher.

The application never receives Docker or host-shell access. It only writes a narrowly
scoped JSON request into the persistent data volume. A root-owned host service validates
that request and executes the fixed protected deployment script.
"""
from __future__ import annotations

import json
import os
import secrets
import time
from pathlib import Path
from typing import Any

DATA_DIR = Path(os.getenv("SHARIPOVAI_DATA_DIR", "/var/lib/sharipovai"))
CONTROL_DIR = DATA_DIR / "deployment_control"
REQUEST_FILE = CONTROL_DIR / "pending.json"
STATUS_FILE = CONTROL_DIR / "status.json"
OWNER_FILE = CONTROL_DIR / "owner.json"
CLAIM_FILE = CONTROL_DIR / "owner_claim.json"
CONFIRM_TTL_SECONDS = 300
DEPLOY_STATUS_STALE_SECONDS = 120
_CONFIRMATIONS: dict[int, tuple[str, float]] = {}


def _canonical_owner_id(name: str) -> int | None:
    """Return a positive canonical Telegram identifier or fail closed."""
    value = os.getenv(name, "").strip()
    try:
        identifier = int(value)
    except (TypeError, ValueError):
        return None
    return identifier if identifier > 0 else None


def _single_env_id(name: str, *, positive: bool) -> int | None:
    """Parse exactly one distinct legacy Telegram identifier from list-compatible env syntax."""
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    values: set[int] = set()
    for part in raw.replace(";", ",").split(","):
        token = part.strip()
        if not token:
            continue
        try:
            identifier = int(token)
        except ValueError:
            return None
        if positive:
            if identifier <= 0:
                return None
        elif identifier == 0:
            return None
        values.add(identifier)
    if len(values) != 1:
        return None
    return next(iter(values))


def expected_bootstrap_owner() -> tuple[int, int | None] | None:
    """Return the configured immutable/bootstrap owner identity, including safe legacy migration."""
    canonical_user_raw = os.getenv("TELEGRAM_OWNER_ID", "").strip()
    canonical_chat_raw = os.getenv("TELEGRAM_OWNER_CHAT_ID", "").strip()
    if canonical_user_raw or canonical_chat_raw:
        # Any explicit canonical configuration takes precedence over legacy migration.
        # A chat without a canonical user is a partial/malformed configuration and must
        # fail closed rather than silently falling back to stale legacy admin identity.
        if not canonical_user_raw:
            return None
        user_id = _canonical_owner_id("TELEGRAM_OWNER_ID")
        if user_id is None:
            return None
        if not canonical_chat_raw:
            return user_id, None
        chat_id = _single_env_id("TELEGRAM_OWNER_CHAT_ID", positive=False)
        return (user_id, chat_id) if chat_id is not None else None

    legacy_user_raw = os.getenv("TELEGRAM_ADMIN_USER_ID", "").strip()
    legacy_chat_raw = os.getenv("TELEGRAM_ADMIN_CHAT_ID", "").strip()
    legacy_user = _single_env_id("TELEGRAM_ADMIN_USER_ID", positive=True)
    legacy_chat = _single_env_id("TELEGRAM_ADMIN_CHAT_ID", positive=False)
    if legacy_user_raw:
        if legacy_user is None:
            return None
        if legacy_chat_raw and legacy_chat is None:
            return None
        return legacy_user, legacy_chat
    if legacy_chat_raw:
        if legacy_chat is None:
            return None
        if legacy_chat > 0:
            # Legacy private-chat deployments commonly configured only the chat id.
            # In a private Telegram chat the positive chat id is the same principal.
            return legacy_chat, legacy_chat
    return None


def admin_ids() -> set[int]:
    values: list[str] = []
    for name in ("TELEGRAM_ADMIN_USER_ID", "TELEGRAM_ADMIN_CHAT_ID"):
        values.extend(os.getenv(name, "").replace(";", ",").split(","))
    try:
        owner = json.loads(OWNER_FILE.read_text(encoding="utf-8"))
        if isinstance(owner, dict):
            values.extend([str(owner.get("user_id", "")), str(owner.get("chat_id", ""))])
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        pass
    result: set[int] = set()
    for value in values:
        try:
            result.add(int(value.strip()))
        except (TypeError, ValueError):
            continue
    return result


def is_admin(actor_id: int | None, chat_id: int | None = None) -> bool:
    configured = admin_ids()
    return bool(configured and ({int(actor_id or 0), int(chat_id or 0)} & configured))


def persisted_owner() -> tuple[int, int] | None:
    """Return the exact persisted owner tuple or fail closed."""
    try:
        owner = json.loads(OWNER_FILE.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(owner, dict):
        return None
    user_id = owner.get("user_id")
    chat_id = owner.get("chat_id")
    if type(user_id) is not int or type(chat_id) is not int:
        return None
    if user_id <= 0 or chat_id == 0:
        return None
    return user_id, chat_id


def is_exact_owner(actor_id: int | None, chat_id: int | None) -> bool:
    """Authorize only the persisted Telegram owner actor in the persisted owner chat."""
    owner = persisted_owner()
    if owner is None:
        return False
    if type(actor_id) is not int or type(chat_id) is not int:
        return False
    return actor_id > 0 and chat_id != 0 and owner == (actor_id, chat_id)


def claim_owner(actor_id: int, chat_id: int, code: str) -> tuple[str, dict[str, Any]]:
    if OWNER_FILE.exists():
        return "Владелец уже настроен. Повторное присвоение запрещено.", {"inline_keyboard": []}
    expected_owner = expected_bootstrap_owner()
    if expected_owner is None:
        return (
            "Канонический владелец Telegram не настроен. Присвоение владельца запрещено.",
            {"inline_keyboard": []},
        )
    if type(actor_id) is not int or type(chat_id) is not int or actor_id <= 0 or chat_id == 0:
        return "Этот Telegram-аккаунт не является назначенным владельцем.", {"inline_keyboard": []}
    expected_user_id, expected_chat_id = expected_owner
    if actor_id != expected_user_id or (
        expected_chat_id is not None and chat_id != expected_chat_id
    ):
        return "Этот Telegram-аккаунт не является назначенным владельцем.", {"inline_keyboard": []}
    try:
        claim = json.loads(CLAIM_FILE.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        claim = {}
    expected = str(claim.get("code", ""))
    expires_at = int(claim.get("expires_at", 0) or 0)
    if not expected or expires_at < int(time.time()):
        return "Код активации отсутствует или истёк. Запусти установку host watcher ещё раз.", {"inline_keyboard": []}
    if not secrets.compare_digest(expected, str(code).strip()):
        return "Неверный код активации владельца.", {"inline_keyboard": []}
    _atomic_write(OWNER_FILE, {
        "user_id": expected_user_id,
        "chat_id": chat_id,
        "claimed_at": int(time.time()),
    })
    try:
        CLAIM_FILE.unlink()
    except OSError:
        pass
    return (
        "✅ <b>Телефон назначен владельцем SharipovAI</b>\n\n"
        "Теперь команды /deploy и /deploy_status доступны только этому Telegram-аккаунту.",
        {"inline_keyboard": deployment_keyboard(actor_id, chat_id)},
    )


def deployment_keyboard(actor_id: int | None, chat_id: int | None) -> list[list[dict[str, Any]]]:
    if not is_exact_owner(actor_id, chat_id):
        return []
    return [[
        {"text": "🔄 Обновить SharipovAI", "callback_data": "deploy:prepare"},
        {"text": "📋 Статус обновления", "callback_data": "deploy:status"},
    ]]


def prepare_confirmation(actor_id: int, chat_id: int) -> tuple[str, dict[str, Any]]:
    if not is_exact_owner(actor_id, chat_id):
        return unauthorized_message(actor_id, chat_id), {"inline_keyboard": []}
    token = secrets.token_urlsafe(10)
    _CONFIRMATIONS[actor_id] = (token, time.time() + CONFIRM_TTL_SECONDS)
    status = read_status()
    running = status.get("state") in {"queued", "running"}
    if running:
        return (
            "⏳ <b>Обновление уже выполняется</b>\n\n"
            f"Этап: <b>{_safe(status.get('stage', 'выполнение'))}</b>\n"
            "Новое обновление нельзя запустить до завершения текущего.",
            {"inline_keyboard": [[{"text": "📋 Обновить статус", "callback_data": "deploy:status"}]]},
        )
    keyboard = {
        "inline_keyboard": [
            [{"text": "✅ Подтвердить обновление", "callback_data": f"deploy:confirm:{token}"}],
            [{"text": "❌ Отмена", "callback_data": "deploy:cancel"}],
        ]
    }
    return (
        "⚠️ <b>Подтверждение обновления</b>\n\n"
        "Будут выполнены только фиксированные действия:\n"
        "• git pull --ff-only из main;\n"
        "• защищённые тесты кандидата;\n"
        "• замена контейнера только после успешной проверки;\n"
        "• автоматический откат при сбое;\n"
        "• VPN-контейнер не затрагивается.\n\n"
        "Реальные биржевые ордера останутся заблокированы.",
        keyboard,
    )


def confirm_deployment(actor_id: int, chat_id: int, token: str) -> tuple[str, dict[str, Any]]:
    if not is_exact_owner(actor_id, chat_id):
        return unauthorized_message(actor_id, chat_id), {"inline_keyboard": []}
    confirmation = _CONFIRMATIONS.pop(actor_id, None)
    if not confirmation or not secrets.compare_digest(confirmation[0], token) or confirmation[1] < time.time():
        return (
            "Подтверждение истекло или уже использовано. Нажми «Обновить SharipovAI» ещё раз.",
            {"inline_keyboard": [[{"text": "🔄 Начать заново", "callback_data": "deploy:prepare"}]]},
        )
    status = read_status()
    if status.get("state") in {"queued", "running"} or REQUEST_FILE.exists():
        return (
            "⏳ Обновление уже находится в очереди или выполняется.",
            {"inline_keyboard": [[{"text": "📋 Статус обновления", "callback_data": "deploy:status"}]]},
        )
    request_id = f"tg-{int(time.time())}-{secrets.token_hex(4)}"
    payload = {
        "version": 1,
        "request_id": request_id,
        "action": "deploy_main",
        "actor_id": actor_id,
        "chat_id": chat_id,
        "created_at": int(time.time()),
    }
    _atomic_write(REQUEST_FILE, payload)
    _atomic_write(STATUS_FILE, {
        "state": "queued",
        "stage": "ожидание host watcher",
        "request_id": request_id,
        "chat_id": chat_id,
        "updated_at": int(time.time()),
    })
    return (
        "✅ <b>Обновление поставлено в очередь</b>\n\n"
        f"ID: <code>{request_id}</code>\n"
        "Host watcher запустит защищённый deploy. Бот пришлёт итог автоматически.",
        {"inline_keyboard": [[{"text": "📋 Проверить статус", "callback_data": "deploy:status"}]]},
    )


def cancel_confirmation(actor_id: int) -> tuple[str, dict[str, Any]]:
    _CONFIRMATIONS.pop(int(actor_id), None)
    return "Обновление отменено. Никаких изменений не выполнено.", {"inline_keyboard": []}


def status_message(actor_id: int | None, chat_id: int | None) -> tuple[str, dict[str, Any]]:
    if not is_exact_owner(actor_id, chat_id):
        return unauthorized_message(actor_id, chat_id), {"inline_keyboard": []}
    status = read_status()
    if not status:
        text = "📋 Обновления с телефона ещё не запускались."
    else:
        labels = {
            "queued": "В ОЧЕРЕДИ",
            "running": "ВЫПОЛНЯЕТСЯ",
            "success": "УСПЕШНО",
            "failed": "ОШИБКА",
            "timeout": "ТАЙМАУТ",
            "rolled_back": "ОТКАЧЕНО",
        }
        state = str(status.get("state", "unknown"))
        text = (
            "📋 <b>Статус обновления</b>\n\n"
            f"Состояние: <b>{labels.get(state, state.upper())}</b>\n"
            f"Этап: {_safe(status.get('stage', '—'))}\n"
            f"ID: <code>{_safe(status.get('request_id', '—'))}</code>\n"
            f"Коммит: <code>{_safe(status.get('commit', '—'))}</code>\n"
            f"Последний прогресс: <code>{_safe(status.get('heartbeat_at', status.get('updated_at', '—')))}</code>\n"
            f"Сообщение: {_safe(status.get('message', '—'))}"
        )
    keyboard = {"inline_keyboard": [[
        {"text": "🔄 Обновить статус", "callback_data": "deploy:status"},
        {"text": "🚀 Новое обновление", "callback_data": "deploy:prepare"},
    ]]}
    return text, keyboard


def read_status() -> dict[str, Any]:
    try:
        value = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
        return _terminalize_stale_status(value) if isinstance(value, dict) else {}
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}


def unauthorized_message(actor_id: int | None, chat_id: int | None) -> str:
    configured = bool(admin_ids())
    if configured:
        return "⛔ Эта команда доступна только владельцу SharipovAI."
    return (
        "🔐 <b>Владелец Telegram ещё не настроен</b>\n\n"
        f"Твой user ID: <code>{int(actor_id or 0)}</code>\n"
        f"Chat ID: <code>{int(chat_id or 0)}</code>\n"
        "После установки host watcher отправь: <code>/claim_owner КОД</code>."
    )


def identity_message(actor_id: int | None, chat_id: int | None) -> str:
    return (
        "🪪 <b>Telegram идентификаторы</b>\n\n"
        f"User ID: <code>{int(actor_id or 0)}</code>\n"
        f"Chat ID: <code>{int(chat_id or 0)}</code>\n"
        f"Права владельца: <b>{'ДА' if is_exact_owner(actor_id, chat_id) else 'НЕТ'}</b>"
    )


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".tmp-{os.getpid()}")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


def _terminalize_stale_status(status: dict[str, Any]) -> dict[str, Any]:
    """Never present an abandoned deployment as still running.

    The host watcher refreshes ``heartbeat_at`` while its bounded deploy child is
    alive.  If that evidence stops, the application atomically closes only the
    matching pending request; a later request cannot be removed accidentally.
    """
    if str(status.get("state", "")).lower() not in {"queued", "running"}:
        return status
    try:
        heartbeat = int(status.get("heartbeat_at", status.get("updated_at", 0)) or 0)
    except (TypeError, ValueError):
        heartbeat = 0
    if heartbeat > 0 and int(time.time()) - heartbeat <= DEPLOY_STATUS_STALE_SECONDS:
        return status

    request_id = str(status.get("request_id") or "")
    terminal = {
        **status,
        "state": "timeout",
        "stage": "stale_status",
        "message": "Нет актуального heartbeat от host watcher; deploy остановлен fail-closed.",
        "updated_at": int(time.time()),
        "heartbeat_at": heartbeat,
    }
    _atomic_write(STATUS_FILE, terminal)
    try:
        pending = json.loads(REQUEST_FILE.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        pending = {}
    if isinstance(pending, dict) and str(pending.get("request_id") or "") == request_id:
        try:
            REQUEST_FILE.unlink()
        except OSError:
            pass
    return terminal


def _safe(value: Any) -> str:
    import html

    return html.escape(str(value), quote=False)
