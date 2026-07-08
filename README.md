# SharipovAI OS

SharipovAI OS — demo-first AI trading analysis system with a FastAPI dashboard, deterministic runner, paper trading, risk checks, intelligence APIs, Telegram worker, and a safety-first exchange connector.

> Safety rule: real trading is disabled. The current system is designed for demo analysis, paper trading, and safe order previews only.

## Main parts

- `dashboard/` — FastAPI web dashboard and HTML UI.
- `runner/` — integrated SharipovAI pipeline runner.
- `paper_trading/` — virtual paper trading engine.
- `risk_engine/`, `portfolio_engine/`, `confidence/`, `consensus/` — decision support modules.
- `exchange_connector/` — safe exchange connector with commission-aware order previews.
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

## Safe exchange connector

The exchange connector is safety-first. It can read environment configuration and calculate order previews, but real order execution is blocked in the current implementation.

Commissions are always counted as cost/loss:

- BUY preview: `total_cost = quantity * price + estimated_fee`.
- SELL preview: `total_cost = quantity * price - estimated_fee`.
- Break-even price includes the estimated fee.

Example environment values:

```env
EXCHANGE_NAME=bybit
EXCHANGE_MODE=sandbox
EXCHANGE_BASE_URL=https://api-testnet.bybit.com
EXCHANGE_API_KEY=your_key_if_needed
EXCHANGE_API_SECRET=your_secret_if_needed
EXCHANGE_DEFAULT_FEE_RATE=0.001
EXCHANGE_LIVE_TRADING_ENABLED=0
```

Do not enable live exchange access until audited order execution, manual approval, and emergency stop controls are implemented.

## Required production environment variables

Set these in Render or another hosting platform:

```env
AUTH_SECRET=long-random-secret
ADMIN_USERNAME=your-admin-login
ADMIN_PASSWORD=strong-admin-password
BOT_TOKEN=new-telegram-bot-token
WEBAPP_URL=https://your-dashboard-url
```

Never commit real secrets, exchange API keys, or Telegram tokens to GitHub.

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
- Exchange connector supports safe previews with commissions, not real execution.
- Access requests are logged for security review; registration does not automatically create an approved login.

## Security checklist

- Rotate any Telegram token that was ever shown in chat or screenshots.
- Keep `AUTH_SECRET` private and strong.
- Keep `ADMIN_PASSWORD` private and strong.
- Keep exchange API keys private and disabled for withdrawals.
- Keep real trading disabled until explicit exchange safeguards and confirmations are implemented.
