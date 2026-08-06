# SharipovAI Memory Layer

## Purpose

Memory Layer stores reusable experience without becoming a second financial source of truth.

- `ProjectDatabase` remains the only physical database owner.
- Financial state, orders, positions, balances and canonical decisions are never read from Memory Layer.
- Memory can store passive work events and return verified context on request.
- Memory has no execution authority and cannot weaken Risk Engine or execution locks.

## Layers

| Layer | Storage | Initial scope |
|---|---|---|
| L0 | `memory_raw_logs` | Passive Learning Engine events and explicitly recorded dialogue |
| L1 | `memory_facts` | Extracted facts with evidence, status and optional embedding |
| L2 | `memory_scenarios` | Schema foundation; automatic aggregation is not enabled |
| L3 | `memory_core` | Schema foundation; automatic persona generation is not enabled |

## Feature flags

All behavior-changing flags are off by default:

```env
MEMORY_ENABLED=false
MEMORY_CONTEXT_INJECTION=false
MEMORY_EXTRACTION_ENABLED=false
MEMORY_VERIFICATION_ENABLED=true
```

Optional extraction configuration uses an OpenAI-compatible endpoint:

```env
MEMORY_LLM_BASE_URL=
MEMORY_LLM_API_KEY=
MEMORY_LLM_MODEL=
MEMORY_EMBEDDING_BASE_URL=
MEMORY_EMBEDDING_API_KEY=
MEMORY_EMBEDDING_MODEL=
```

No key is required while extraction and embeddings are disabled.

## Status policy

```text
EXTRACTED -> VERIFIED -> ACTIVE
     |          |          |
     +------> REVOKED <----+
     +------> SUPERSEDED <-+
```

`ACTIVE` is never assigned automatically. Activation requires an existing canonical `agent_decisions` record with:

- `kind=memory_fact_activation`;
- `status=approved`;
- `security_verdict=allow`;
- `metadata.fact_id` equal to the target fact;
- an authenticated internal service request.

This reuses the existing Telegram owner-approval ledger instead of creating a second approval mechanism.

## Runtime safety

- When `MEMORY_ENABLED=false`, no memory tables are created and no worker starts.
- Repeated failures open an in-process circuit breaker. The rest of SharipovAI continues running.
- Secret-like values are redacted before L0 persistence.
- Context retrieval returns only `VERIFIED` and `ACTIVE` facts.
- Returned context is labelled non-authoritative.
- LLM extraction cannot activate facts.
- The runtime worker is daemonized and bounded by batch and polling limits.

## API

- `GET /api/memory/health`
- `GET /api/memory/stats`
- `POST /api/memory/context`
- `POST /internal/memory/facts/{fact_id}/activate` — internal service + approved decision only

Dashboard memory routes remain protected by the existing global authentication guard. No new public management endpoint is introduced.

## Rollout

1. Deploy with all Memory flags false.
2. Confirm `/health`, authenticated `/api/system/health` and authenticated `/api/memory/health`.
3. Enable only `MEMORY_ENABLED=true`; verify passive L0 collection.
4. After reviewing storage volume and backups, enable extraction.
5. Review `EXTRACTED`/`VERIFIED` quality and cost. Do not activate facts automatically.
6. Enable context injection only for one non-execution agent first.
7. Never use Memory Layer as balance, PnL, order or position truth.

## Rollback

Disable all Memory flags and restart the application. This stops every Memory behavior without changing data.

Schema removal is optional and destructive. It requires a visible backup and explicit confirmation:

```bash
MEMORY_ENABLED=false bash scripts/rollback_memory_migrations.sh
MEMORY_ENABLED=false bash scripts/rollback_memory_migrations.sh --confirm-drop-memory
```

The rollback removes only Memory Layer tables. Existing project, execution, evidence and learning tables are untouched.
