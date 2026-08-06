# Deployment and rollback

## Memory Layer safe deployment

The Memory Layer ships disabled. Do not commit `.env.vps` or secrets.

Add these values to the server-side environment only after the PR is merged:

```env
MEMORY_ENABLED=false
MEMORY_CONTEXT_INJECTION=false
MEMORY_EXTRACTION_ENABLED=false
MEMORY_VERIFICATION_ENABLED=true
```

Deploy through the existing backup-first updater. The verified canonical database backup automatically covers the new tables because they live in the same `ProjectDatabase`.

### Post-deploy checks with flags off

```bash
curl --fail http://127.0.0.1:8000/health
```

Open `/api/memory/health` through an authenticated dashboard session. Expected Memory status: `disabled`. Existing trading behavior must be unchanged.

### Passive collection rollout

Set only `MEMORY_ENABLED=true`, recreate the application container through the existing safe updater, and verify:

- application health remains 200;
- authenticated `/api/memory/health` reports schema version 1;
- `execution_authority=false`;
- `automatic_activation=false`;
- Mainnet/Testnet flags remain disabled and the kill switch remains active.

### Extraction rollout

Configure `MEMORY_LLM_*`, then enable `MEMORY_EXTRACTION_ENABLED=true`. Extracted facts remain `EXTRACTED` or `VERIFIED`; they do not enter trading decisions.

### Context rollout

Enable `MEMORY_CONTEXT_INJECTION=true` only after fact-quality review. Context is available by explicit API/helper calls and cannot override current evidence or canonical Risk Engine.

## Rollback

Fast rollback: set all Memory behavior flags to false and recreate only the application container through the normal deployment process.

Destructive schema rollback is separate and requires a non-empty backup:

```bash
MEMORY_ENABLED=false bash scripts/rollback_memory_migrations.sh
MEMORY_ENABLED=false bash scripts/rollback_memory_migrations.sh --confirm-drop-memory
```

Never run destructive rollback while Memory Layer is enabled.
