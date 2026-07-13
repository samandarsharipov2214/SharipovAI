# SharipovAI Constitution

Version: `2026.07-safety-foundation-v2`  
Status: Binding development and runtime policy

This document defines non-negotiable rules. Code, configuration, dashboards,
AI outputs and deployment automation must obey it.

## 1. Capital protection

1. Preservation of capital has priority over activity, speed and profit.
2. Mainnet execution is compiled out at the current development stage.
3. Environment variables, Telegram commands, dashboard requests and LLM output
   cannot override the mainnet compile lock.
4. API keys used by SharipovAI must never have withdrawal or transfer rights.
5. A future live stage requires a separate limited subaccount and explicit owner
   approval. It is not enabled by this repository state.

## 2. Execution stages

Allowed progression:

```text
READ_ONLY -> PAPER -> TESTNET -> CONTROLLED_MAINNET -> SCALE
```

Skipping a stage is forbidden.

- `READ_ONLY`: market/account reads only.
- `PAPER`: virtual balance and virtual fills using real market evidence.
- `TESTNET`: exchange writes only through an `ApprovedExecutionRequest`.
- `CONTROLLED_MAINNET`: currently unavailable because mainnet is compiled out.
- `SCALE`: never automatic; requires owner approval and verified performance.

## 3. Canonical decision path

```text
Market Intelligence
  -> Portfolio snapshot
  -> Risk Engine
  -> Decision Quality
  -> Security Guard
  -> TradingCandidate validation
  -> ApprovedExecutionRequest
  -> Testnet executor
```

No dashboard, Telegram handler, Learning Engine, agent or LLM may call an order
creation endpoint directly.

## 4. Fail-closed rules

Missing, stale, contradictory or non-finite required data means `BLOCK`.

Mandatory blocks include:

- active kill switch;
- stale market data;
- missing portfolio, cost or risk evidence;
- expired candidate or execution request;
- unknown instrument specification;
- exceeded notional, exposure, drawdown or loss limits;
- duplicate candidate or order identity;
- Mainnet environment;
- secrets or credentials in logs, Evidence or Git history.

## 5. Paper-trading realism

Only capital and fills are virtual. Quotes, timestamps, fees, spread, slippage,
funding, risk, drawdown and Evidence must be treated as production data.

Paper state must be persistent, atomic, revisioned and recoverable from a
last-known-good backup. Synthetic historical prices and fabricated trades are
forbidden.

## 6. Canonical architecture

SharipovAI has nine top-level AI organs:

1. General Controller
2. Market Intelligence
3. News Intelligence
4. Risk Engine
5. Portfolio Engine
6. Virtual Execution
7. Decision Quality
8. Learning Engine
9. Security Guard

New capabilities extend an existing owner unless the responsibility is genuinely
unique. Interfaces, storage, monitoring and transport are not new AI organs.

## 7. Learning and strategy changes

Learning may create proposals, lessons and challenger strategies. It may not:

- edit production rules automatically;
- enable exchange writes;
- increase live capital;
- remove risk or security vetoes;
- treat confidence as proof of profitability.

Promotion requires reproducible tests, out-of-sample evidence and General
Controller approval.

## 8. Repository and CI rules

A change is mergeable only when:

- Python compilation succeeds;
- the hard execution-lock check succeeds;
- targeted safety tests succeed;
- the complete pytest suite succeeds;
- no secret or runtime state is committed;
- the change has an explicit rollback path;
- testnet and live flags remain disabled unless the PR is specifically authorized.

A static audit percentage never overrides a failed or skipped full test suite.

## 9. Profit claims

SharipovAI reports measured results after fees and execution costs. It must not
promise guaranteed income, fabricate performance or scale capital based only on
backtests, confidence scores or AI narrative.

## Change history

| Version | Date | Summary |
| --- | --- | --- |
| `2026.07-safety-foundation-v2` | 2026-07-14 | Mainnet compile lock, canonical execution request, atomic paper state and truthful CI policy. |
