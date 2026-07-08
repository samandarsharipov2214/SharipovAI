"""Create a Telethon StringSession for SharipovAI.

Run this locally in a trusted terminal, not inside GitHub and not in chat:

    python scripts/create_telegram_session.py

It will ask for TELEGRAM_API_ID / TELEGRAM_API_HASH and your Telegram login code.
Copy only the printed TELEGRAM_SESSION_STRING into Render Environment Variables.
Never commit the session string and never send it to anyone.
"""

from __future__ import annotations

import asyncio
import getpass

from telethon import TelegramClient
from telethon.sessions import StringSession


async def main() -> None:
    """Create and print a Telegram StringSession."""

    api_id_raw = input("TELEGRAM_API_ID: ").strip()
    api_hash = getpass.getpass("TELEGRAM_API_HASH: ").strip()
    if not api_id_raw.isdigit() or not api_hash:
        raise SystemExit("API ID/API HASH are required.")
    async with TelegramClient(StringSession(), int(api_id_raw), api_hash) as client:
        print("Login started. Enter phone/code/password if Telegram asks.")
        await client.start()
        session = client.session.save()
        print("\nTELEGRAM_SESSION_STRING=")
        print(session)
        print("\nStore this only in Render Environment Variables. Do not commit it.")


if __name__ == "__main__":
    asyncio.run(main())
