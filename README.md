# SharipovAI OS

SharipovAI is a safety-first AI trading operating system built around verified
market evidence, deterministic risk controls, persistent paper trading,
event-driven strategy research and guarded exchange integration.

> **Current safety state:** Mainnet execution is compiled out. Testnet is disabled
> by default and can write only through a short-lived `ApprovedExecutionRequest`
> with a durable idempotency reservation. An unresolved execution blocks restart.

SharipovAI does not guarantee profit. Its job is to determine whether a strategy
has positive expectancy after spread, fees, slippage, drawdown and execution
failure modes.

## Architecture

The canonical architecture has nine AI organs:

1. General Controller
2. Market Intelligence
3. News Intelligence
4. Risk Engine
5. Portfolio Engine
6. Virtual Execution
7. Decision Quality
8. Learning Engine
9. Security Guard

`ai_architecture_registry.py` is the ownership source of truth. Infrastructure
such as storage, execution idempotency and backtesting does not become another AI.

## Safety invariants

- `MAINNET_EXECUTION_COMPILED=False` cannot be overridden by environment variables.
- `EXECUTION_KILL_SWITCH=1` is the safe default.
- Dashboard, Telegram, agents, strategies and LLM output cannot create orders.
- The legacy `place_market_order()` entry point is removed.
- Exchange writes use `BybitExecutionClient.execute(ApprovedExecutionRequest)`.
- Every request has a deterministic `sai_...` `orderLinkId` and is reserved in
  `ProjectDatabase` before the HTTP call.
- Duplicate and unresolved intents are blocked; transport timeouts are reconciled,
  never retried blindly.
- Startup compares idempotency reservations, execution journal and private Bybit
  order state before Testnet may continue.
- Paper state is atomic, revisioned and recoverable.
- Secrets, account snapshots, runtime databases and execution journals stay out of Git.

Binding policy: [`CONSTITUTION.md`](CONSTITUTION.md).

## Main components

| Component | Responsibility |
| --- | --- |
| `dashboard/` | FastAPI dashboard, APIs and operational views |
| `trading_candidate.py` | Fail-closed analytical candidate contract |
| `exchange_connector/execution_contract.py` | Immutable approved execution envelope |
| `exchange_connector/execution_idempotency.py` | Durable duplicate/unresolved protection |
| `exchange_connector/bybit_order_identity.py` | Canonical deterministic order identity registry |
| `exchange_connector/bybit_order_state.py` | Private order lifecycle and partial-fill state |
| `autonomous_trading/startup_reconciliation.py` | Restart reconciliation and fail-closed gate |
| `autonomous_trading/testnet_bridge.py` | Fresh paper-candidate to Testnet mirror |
| `capital_allocation.py` | Reserve, risk, symbol and correlation exposure allocation |
| `risk_engine/` | Hard limits, soft score and position-size multiplier |
| `trading_core/` | Shared market, signal, fill, cost and event-driven backtest models |
| `paper_activity_engine.py` | Durable virtual-account state |
| `storage/` | Canonical shared database and Evidence ledger |

## Canonical execution path

```text
Verified market evidence
  -> Portfolio snapshot
  -> Risk Engine hard limits
  -> Capital allocation
  -> Decision Quality
  -> Security Guard
  -> TradingCandidate validation
  -> ApprovedExecutionRequest
  -> Idempotency reservation
  -> Bybit Testnet submission
  -> Private order state
  -> Reconciliation
  -> Outcome/Learning Evidence
```

New execution code:

```python
validation = validate_trading_candidate(candidate, now_ms=now_ms)
request = build_execution_request(
    candidate,
    validation,
    quantity=quantity,
    now_ms=now_ms,
)
result = BybitExecutionClient(database=database).execute(
    request,
    now_ms=now_ms,
)
```

A timeout after submission leaves the request unresolved. The same request cannot
be sent again until reconciliation resolves its state.

## Risk and capital defaults

| Rule | Default |
| --- | ---: |
| Reserve | 20% |
| Maximum total exposure | 80% |
| Maximum one position | 20% |
| Maximum one symbol | 20% |
| Maximum correlated group | 35% |
| Maximum risk per trade | 1% |
| Daily loss stop | 2% |
| Portfolio drawdown stop | 10% |
| Leverage | 1× |

Hard blocks include stale data, active kill switch, invalid instruments,
drawdown/loss limits, exposure limits, liquidity floor and maximum positions.
Soft risk only scales size: `LOW=100%`, `MEDIUM=60%`, `HIGH=25%`,
`CRITICAL=0%`.

## Event-driven backtesting

`trading_core.EventDrivenBacktester` provides a shared research foundation:

- immutable chronological market events;
- explicit bid and ask;
- fees and slippage on every fill;
- shared capital allocation and correlation caps;
- mark-to-market equity and maximum drawdown;
- no future lookup or synthetic fill generation.

Example:

```python
from trading_core import EventDrivenBacktester, MarketEvent, Side, Signal

class Strategy:
    def on_market(self, event, portfolio):
        if event.symbol not in portfolio.positions:
            return Signal(Side.BUY, requested_risk_percent=1.0, reason="entry")
        return None

result = EventDrivenBacktester().run(
    [MarketEvent(1, "BTCUSDT", bid=99.0, ask=100.0)],
    Strategy(),
)
print(result.net_pnl, result.max_drawdown_percent)
```

Backtest evidence alone never enables Mainnet. Funding, latency, instrument steps
and walk-forward/out-of-sample validation are required before promotion.

## Local setup

Python 3.12 is required.

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

Never commit a populated `.env`.

## Safety and quality checks

```bash
python -m pip check
python -m pip_audit -r requirements.txt --progress-spinner off
python -m compileall -q .

python -m pytest \
  tests/test_execution_contract.py \
  tests/test_execution_idempotency.py \
  tests/test_startup_reconciliation.py \
  tests/test_risk_hard_limits.py \
  tests/test_capital_allocation.py \
  tests/test_trading_core_backtest.py \
  -q --tb=short

python -m pytest -q --tb=short
```

CI additionally records critical-module coverage, JUnit output, full pytest logs
and a compact failure report. A partial or skipped suite is not a green release.

## Safe environment defaults

```env
EXCHANGE_MODE=sandbox
EXCHANGE_BASE_URL=https://api-testnet.bybit.com
EXCHANGE_LIVE_TRADING_ENABLED=0
LIVE_EXECUTION_MANUAL_UNLOCK=0
AUTONOMOUS_TESTNET_BRIDGE_ENABLED=0
AUTONOMOUS_TESTNET_ENABLED=0
TESTNET_EXECUTION_ENABLED=0
EXECUTION_KILL_SWITCH=1
EXECUTION_MAX_NOTIONAL_USDT=25
TESTNET_MIRROR_MAX_TRADE_AGE_MS=5000

VIRTUAL_ACCOUNT_RESERVE_PERCENT=20
VIRTUAL_ACCOUNT_MAX_TOTAL_EXPOSURE_PERCENT=80
VIRTUAL_ACCOUNT_MAX_POSITION_PERCENT=20
VIRTUAL_ACCOUNT_MAX_SYMBOL_EXPOSURE_PERCENT=20
VIRTUAL_ACCOUNT_MAX_CORRELATED_EXPOSURE_PERCENT=35
VIRTUAL_ACCOUNT_MAX_RISK_PER_TRADE_PERCENT=1
VIRTUAL_ACCOUNT_MAX_DAILY_LOSS_PERCENT=2
```

These settings do not enable exchange writes. Testnet additionally requires
isolated Testnet credentials and completed safety/stage gates. Mainnet remains
unavailable even if every environment flag is changed.

## Dashboard

```bash
uvicorn dashboard:app --reload
```

Open `http://127.0.0.1:8000`.

Production:

```bash
uvicorn dashboard:app --host 0.0.0.0 --port "$PORT"
```

## Development workflow

1. Work in a branch and keep PRs draft until factual checks pass.
2. Keep Testnet/Mainnet disabled by default.
3. Add tests for every execution, risk, persistence and strategy change.
4. Run dependency audit, critical coverage and complete pytest.
5. Review the diff for secrets and safety-flag changes.
6. Resolve every ambiguous execution through reconciliation.
7. Merge only after factual green checks and a documented rollback.

Design documents:

- `CONSTITUTION.md`
- `AGENTS.md`
- `docs/crypto-trading-ai-architecture.md`
- `docs/capital-allocation-policy.md`
- `docs/ecc-adoption-plan.md`

## Security

- Rotate any token or key exposed in chat, screenshots or logs.
- Separate read-only, Testnet and future Mainnet credentials.
- Disable withdrawals and transfers for automated keys.
- Keep production secrets outside Git and Evidence payloads.
- Treat unexpected account, position or order state as a kill-switch event.
