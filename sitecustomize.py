"""Startup helpers for SharipovAI.

Python imports sitecustomize automatically when this file is on sys.path.
It loads local .env values and also autostarts the Telegram bot when Render runs
only the web service command:
    uvicorn dashboard.app:app --host 0.0.0.0 --port $PORT
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

_STARTED_TELEGRAM_BOT = False


def _load_dotenv() -> None:
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _should_start_telegram_bot() -> bool:
    if os.getenv("TELEGRAM_AUTOSTART_DISABLED", "").lower() in {"1", "true", "yes"}:
        return False
    if not os.getenv("BOT_TOKEN", "").strip():
        return False
    command = " ".join(sys.argv).lower()
    return "uvicorn" in command or bool(os.getenv("RENDER")) or bool(os.getenv("RENDER_SERVICE_ID"))


def _start_telegram_bot_once() -> None:
    global _STARTED_TELEGRAM_BOT
    if _STARTED_TELEGRAM_BOT or not _should_start_telegram_bot():
        return
    _STARTED_TELEGRAM_BOT = True

    def _run() -> None:
        try:
            from telegram_bot import poll

            poll()
        except Exception as exc:
            print(f"SharipovAI Telegram autostart failed: {exc}", flush=True)

    threading.Thread(target=_run, name="sharipovai-telegram-bot", daemon=True).start()
    print("SharipovAI Telegram bot autostart enabled", flush=True)


_load_dotenv()
_start_telegram_bot_once()
