# SharipovAI — Agent/Codex Operating Guide

## Core rule
Only the account balance and order execution are virtual. News, risk, portfolio,
learning, evidence, security, Telegram, website, audit, and monitoring must use
real runtime state and honest freshness. Never replace missing live data with
sample/demo content.

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
```

Then verify imports:

```bash
python -c "import dashboard; print(dashboard.app.title)"
python -c "from news_monitor.agent_network import run_due_agents; print(run_due_agents(force=True)['status'])"
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
