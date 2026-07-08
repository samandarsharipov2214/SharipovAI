# SharipovAI OS

SharipovAI OS — demo-first AI trading analysis system with a FastAPI dashboard, deterministic runner, paper trading, risk checks, intelligence APIs, and a Telegram worker.

> Safety rule: real trading is disabled. The current system is designed for demo analysis and paper trading only.

## Main parts

- `dashboard/` — FastAPI web dashboard and HTML UI.
- `runner/` — integrated SharipovAI pipeline runner.
- `paper_trading/` — virtual paper trading engine.
- `risk_engine/`, `portfolio_engine/`, `confidence/`, `consensus/` — decision support modules.
- `telegram_bot.py` — Telegram long-polling worker using the Telegram Bot HTTP API directly.
- `config/default.toml` — default demo configuration.

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Run tests

```bash
python -m pytest
```

## Run dashboard locally

```bash
uvicorn dashboard.app:app --reload
```

Open:

```text
http://127.0.0.1:8000
```

## Run Telegram bot locally

Set environment variables first:

```bash
export BOT_TOKEN="your_new_bot_token"
export WEBAPP_URL="https://your-dashboard-url.example.com"
```

Then run:

```bash
python telegram_bot.py
```

Important: the bot file is `telegram_bot.py`, not `bot.py`.

## Required production environment variables

Set these in Render or another hosting platform:

```env
AUTH_SECRET=long-random-secret
ADMIN_USERNAME=your-admin-login
ADMIN_PASSWORD=strong-admin-password
BOT_TOKEN=new-telegram-bot-token
WEBAPP_URL=https://your-dashboard-url
```

Never commit real secrets or Telegram tokens to GitHub.

## Render start commands

Web service:

```bash
uvicorn dashboard.app:app --host 0.0.0.0 --port $PORT
```

Telegram worker:

```bash
python telegram_bot.py
```

## Current limits

- The runner uses deterministic demo data in `demo` mode.
- Telegram bot currently opens the Mini App and shows basic menu replies.
- Paper trading state is reset by the current runner flow and is not yet persistent.
- Access requests are logged for security review; registration does not automatically create an approved login.

## Security checklist

- Rotate any Telegram token that was ever shown in chat or screenshots.
- Keep `AUTH_SECRET` private and strong.
- Keep `ADMIN_PASSWORD` private and strong.
- Keep real trading disabled until explicit exchange safeguards and confirmations are implemented.
