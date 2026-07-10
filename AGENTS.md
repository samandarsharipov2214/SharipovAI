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

## Failure isolation
One failed AI must not crash the whole audit, Telegram webhook, dashboard startup,
or other agents. Report the failed module with its exact error and continue.

## Verification after changes
Run at minimum:

```bash
python -m pytest news_monitor/tests/test_agent_network.py
python -m pytest dashboard/tests/test_news_agent_network_api.py
python -m pytest dashboard/tests/test_bot_communication_dashboard_integration.py
python -m pytest dashboard/tests/test_evidence_vault_dashboard_integration.py
python -m pytest dashboard/tests/test_learning_os_dashboard_integration.py
python -m pytest tests/test_ai_architecture_registry.py
```

Then verify imports:

```bash
python -c "import dashboard; print(dashboard.app.title)"
python -c "from news_monitor.agent_network import run_due_agents; print(run_due_agents(force=True)['status'])"
python -c "from ai_architecture_registry import architecture_snapshot; print(architecture_snapshot()['canonical_ai_count'])"
```

Production checks after Render deploy:
- `/api/social-news/rss/refresh`
- `/api/news-agents/status`
- `/api/realtime/status`
- `/news-agents`
- Telegram `/news`, `/audit`, `/status`

## Safety
- Never enable real exchange order placement automatically.
- Never print secrets or tokens.
- Keep `real_orders_blocked=true` unless the user explicitly completes a separate manual safety approval process.
