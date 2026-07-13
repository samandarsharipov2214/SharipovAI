# SharipovAI OS

SharipovAI is a safety-first AI trading operating system built around real market
evidence, deterministic risk controls, persistent paper trading and guarded
exchange integration.

> **Current safety state:** Mainnet execution is compiled out. Paper trading is
> active development functionality. Testnet execution requires explicit flags,
> credentials, a kill-switch release and an `ApprovedExecutionRequest`.

SharipovAI does not guarantee profit. The project is designed to measure whether
a strategy has positive expectancy after fees, spread, slippage and risk.

## Core architecture

The canonical architecture contains nine AI organs:

1. General Controller
2. Market Intelligence
3. News Intelligence
4. Risk Engine
5. Portfolio Engine
6. Virtual Execution
7. Decision Quality
8. Learning Engine
9. Security Guard

The source of truth is `ai_architecture_registry.py`. New functions extend an
existing owner instead of creating duplicate top-level agents.

## Safety invariants

- Mainnet execution is hard-blocked in code.
- `EXECUTION_KILL_SWITCH=1` is the safe default.
- Testnet and Mainnet credentials are separated.
- Exchange keys must never have withdrawal or transfer permissions.
- Dashboard, Telegram, agents and LLM output cannot call order creation directly.
- Exchange-bound writes use `exchange_connector.ApprovedExecutionRequest`.
- Missing or stale required evidence means `BLOCK`.
- Secrets, runtime databases, account snapshots and journals are ignored by Git.
- Paper state uses atomic writes and a last-known-good backup.

See [`CONSTITUTION.md`](CONSTITUTION.md) for the binding rules.

## Main components

| Component | Responsibility |
| --- | --- |
| `dashboard/` | FastAPI dashboard, APIs and operational views |
| `trading_candidate.py` | Fail-closed candidate evidence contract |
| `exchange_connector/` | Read/preview clients and guarded testnet execution |
| `market_paper_engine.py` | Market-backed virtual account execution |
| `paper_activity_engine.py` | Durable atomic virtual-account state |
| `capital_allocation.py` | Reserve, position and risk-based allocation |
| `risk_engine/` | Deterministic vetoes and risk evaluation |
| `portfolio_engine/` | Capital, exposure, fees and PnL ownership |
| `learning/` | Controlled lessons and proposals; no self-deploy |
| `storage/` | Canonical project database and Evidence ledger |
| `news_monitor/` | Specialized real-news agent network |
| `telegram_bot.py` | Telegram interface and owner controls |

## Local setup

Python 3.12 is required.

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Create local configuration from examples only. Never commit a populated `.env`.

## Run the safety checks

```bash
python -m compileall -q .

python -m pytest \
  tests/test_execution_contract.py \
  tests/test_capital_allocation.py \
  tests/test_market_paper_engine.py \
  tests/test_paper_state_recovery.py \
  tests/test_project_change_ledger.py \
  -q --tb=short

python -m pytest -q --tb=short
```

A static audit percentage is not a substitute for a completed full test suite.

## Run the dashboard

```bash
uvicorn dashboard:app --reload
```

Open `http://127.0.0.1:8000`.

Production start command:

```bash
uvicorn dashboard:app --host 0.0.0.0 --port "$PORT"
```

## Safe environment defaults

```env
EXCHANGE_MODE=sandbox
EXCHANGE_BASE_URL=https://api-testnet.bybit.com
EXCHANGE_LIVE_TRADING_ENABLED=0
LIVE_EXECUTION_MANUAL_UNLOCK=0
TESTNET_EXECUTION_ENABLED=0
EXECUTION_KILL_SWITCH=1
EXECUTION_MAX_NOTIONAL_USDT=25

VIRTUAL_ACCOUNT_AUTORUN_ENABLED=1
VIRTUAL_ACCOUNT_TICK_SECONDS=60
VIRTUAL_ACCOUNT_MAX_OPEN=8
VIRTUAL_ACCOUNT_RESERVE_PERCENT=20
VIRTUAL_ACCOUNT_MAX_POSITION_PERCENT=20
VIRTUAL_ACCOUNT_MAX_RISK_PER_TRADE_PERCENT=1
VIRTUAL_ACCOUNT_MIN_NOTIONAL_USDT=25
```

These values do not enable exchange writes. Testnet still requires isolated
credentials and all gates. Mainnet remains unavailable even when environment
variables are changed.

## Execution path

```text
Market data
  -> Portfolio snapshot
  -> Risk decision
  -> Decision Quality
  -> Security Guard
  -> TradingCandidate validation
  -> ApprovedExecutionRequest
  -> Bybit testnet executor
```

`BybitExecutionClient.place_market_order()` remains a temporary testnet-only
compatibility method. New code must call `execute(ApprovedExecutionRequest)`.
The compatibility path cannot execute in live mode.

## Paper-trading state

The virtual account uses real market evidence while balances and fills remain
virtual. State files are written atomically, revisioned and backed up as
`<state-file>.bak`. If the primary JSON is damaged, the engine loads the last
valid backup and reports recovery in its state.

Paper results must include fees and should be extended with measured spread,
slippage and funding before strategy promotion.

## Development workflow

1. Work in a branch.
2. Keep Mainnet and Testnet disabled by default.
3. Add tests with every risk, execution or persistence change.
4. Run targeted safety tests.
5. Run full pytest.
6. Review the diff for secrets and safety-flag changes.
7. Merge only after factual green checks.

Useful design documents:

- `CONSTITUTION.md`
- `AGENTS.md`
- `docs/crypto-trading-ai-architecture.md`
- `docs/capital-allocation-policy.md`
- `docs/ecc-adoption-plan.md`

## Security

- Rotate any token or key ever exposed in chat, screenshots or logs.
- Use separate read-only, Testnet and future Mainnet API keys.
- Disable withdrawals and transfers for all automated keys.
- Keep production secrets outside Git and outside Evidence payloads.
- Treat unexpected account, position or order state as a kill-switch event.
