# SharipovAI — Agent/Codex Operating Guide

## Core rule
Only the account balance and order execution are virtual. News, risk, portfolio,
learning, evidence, security, Telegram, website, audit, and monitoring must use
real runtime state and honest freshness. Never replace missing live data with
sample/demo content.

## Canonical AI architecture
The single source of truth is `ai_architecture_registry.py`.

SharipovAI has 9 canonical AI organs:
1. `general_controller` — coordination, supervision, health monitoring and recovery orchestration.
2. `market_intelligence` — quotes, trend, liquidity, volatility and market regime.
3. `news_intelligence` — real news collection, verification, credibility and specialized news agents.
4. `risk_engine` — limits, drawdown, blocking and stress scenarios.
5. `portfolio_engine` — capital, positions, PnL, fees, reports and rebalancing.
6. `virtual_execution` — virtual-account execution only.
7. `decision_quality` — confidence, consensus and conflict detection.
8. `learning_engine` — lessons, mistakes, rules, exams and improvement proposals.
9. `security_guard` — access, secrets, policies and real-order lock.

Resolved overlaps:
- Supervisor is a capability/submodule of General Controller, not a separate AI.
- Stress Lab is a Risk Engine submodule, not a separate top-level AI.
- Reports are owned by Portfolio Engine.
- Confidence and Consensus are one Decision Quality organ.
- Specialized News agents are children of News Intelligence.
- Telegram and Mini App are interfaces, not AI organs.
- Evidence Vault is storage, not an AI organ.

Before adding an AI:
1. Call/check `responsibility_owner()` in `ai_architecture_registry.py`.
2. If one owner exists, extend it.
3. If several owners match, merge/disambiguate responsibilities.
4. Create a new organ only for a genuinely unique capability.

## Specialized News AI network
Primary implementation:
- `news_monitor/agent_network.py`
- `dashboard/news_agent_network_api.py`

Required properties for every news agent:
- independent `interval_seconds` and due-cycle;
- `last_run_at`, `last_seen`, `data_freshness_seconds`;
- owned sources/categories;
- persistent memory and event output;
- health/status (`active`, `stale`, `waiting_credentials`, `error`);
- explicit routes to downstream organs;
- no implicit `demo_items()` fallback.

Runtime endpoints:
- `GET /api/news-agents/status`
- `GET /api/news-agents/{agent_id}`
- `POST /api/news-agents/{agent_id}/run`
- `POST /api/news-agents/run-all`
- `GET /news-agents`

## Crypto trading and Bybit
The project-wide source of truth is `docs/crypto-trading-ai-architecture.md`.
Read it when changing crypto-trading architecture, organ ownership,
execution/risk boundaries, or when adding a trading subsystem. For isolated
implementation, tests, or documentation changes, read only the relevant
sections when needed.

The official `skills/bybit-trading/SKILL.md` is a Bybit transport/protocol skill,
not a new decision-making AI. It must stay behind the canonical organs and must
never bypass Risk Engine, Decision Quality, General Controller or Security Guard.

SharipovAI project rules override conflicting vendor defaults in that skill:
- do not auto-update the skill or write downloaded modules during normal task execution;
- use the skill only for Bybit transport/protocol work; it does not authorize trading decisions or real execution;
- Mainnet writes remain blocked by SharipovAI policy; a skill-level `CONFIRM` does not unlock them;
- use Testnet writes only when the task explicitly requires integration testing;
- missing live data remains unavailable; never substitute simulated values;
- infer spot/derivatives category from task context when clear, and ask only when ambiguity remains and would change the operation.

Ownership rules:
- market feeds, orderbook, funding, open interest and regime → `market_intelligence`;
- crypto news and market-impact evidence → `news_intelligence`;
- limits, drawdown, leverage, liquidity and stress blocking → `risk_engine`;
- balance, exposure, fees, funding, slippage and reports → `portfolio_engine`;
- confidence, consensus and Trade Gate → `decision_quality`;
- virtual/paper lifecycle → `virtual_execution`;
- lessons, backtests and rule proposals → `learning_engine`;
- API permissions, secrets, account-data access, confirmation and kill switch → `security_guard`;
- orchestration, health and recovery → `general_controller`.

Do not create top-level AIs named Technical AI, Liquidity AI, Exchange Cost AI,
Trade Gate AI, Execution AI, Backtest AI or Bybit AI when the capability belongs
to one of the owners above. Implement them as submodules/services with explicit
inputs, outputs, freshness, evidence and health.

Trading invariants:
- no LLM response may call an order-create endpoint directly;
- missing/stale/unverified required data means `BLOCK`;
- instrument limits must be loaded dynamically, never hard-coded as permanent;
- every order needs a unique `orderLinkId` and asynchronous status confirmation;
- Testnet and Mainnet writes require separate gates;
- Mainnet remains locked without manual approval, kill-switch checks and evidence;
- API keys must not have Withdraw permission and secrets must never be logged.

## Failure isolation
One failed AI must not crash the whole audit, Telegram webhook, dashboard startup,
or other agents. Report the failed module with its exact error and continue.

## Fact-forcing before changes
Before editing a critical file or creating a new subsystem, gather concrete facts
instead of relying on self-evaluation:

1. list the importers, callers, routes and state files affected by the change;
2. identify public functions/classes and data-schema fields that can change;
3. check whether an existing canonical owner or implementation already serves the purpose;
4. define the rollback path before any destructive or production-facing action;
5. name the exact tests/audits that will verify the change.

Do not quote or expose raw production secrets while inspecting schemas. Use field
names and redacted/synthetic examples only.

## Project change ledger
Significant repository, deployment, configuration and runtime changes must be
recordable through `storage.ProjectChangeLedger` using the canonical
`ProjectDatabase`.

Required lifecycle:
- `planned` before mutation;
- `applied` after the intended change exists;
- `verified` only after factual checks pass;
- `failed` or `rolled_back` when verification does not pass.

Ledger operations must use repository-relative traversal-free paths, declare
`managed` or `shared` ownership, and never contain tokens, passwords, API keys,
credentials or private keys. Confidence, a static audit percentage or an LLM
statement is not verification evidence.

The selective ECC adaptation rules and rollout order are fixed in
`docs/ecc-adoption-plan.md`. Do not install or copy the full ECC agent/skill/hook
surface into SharipovAI.

## Verification after changes
Run the smallest relevant tests and checks that verify the changed behavior.
Expand to broader subsystem tests when a change crosses subsystem boundaries,
changes shared contracts, or is being prepared for release/deployment.

Use import/runtime smoke checks only when the affected code path requires them.
After a production deploy, verify the affected endpoints and dependent health
checks; run the full production health suite only for broad releases.

## Safety
- Never enable real exchange order placement automatically.
- Never print secrets or tokens.
- Keep `real_orders_blocked=true` unless the user explicitly completes a separate manual safety approval process.
