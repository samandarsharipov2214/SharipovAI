# Deploy reproducibility (F07 / F08)

## F07 — Rollback image retention

Production images are often tagged with mutable deploy-prefixed names such as
`sharipovai:deploy-<sha12>-<epoch>-<pid>` (see `scripts/deploy_market_paper_runtime.sh`).
Rollback **must not** assume `sharipovai:<sha12>` already exists.

**Source of truth** for the currently running release:

1. the running `sharipovai` container's image ID (`sha256:<64 hex>`)
2. that image's OCI label `org.opencontainers.image.revision`

Before a candidate build, deploy scripts:

1. resolve the running image ID
2. verify `org.opencontainers.image.revision == <previous_sha>`
3. `docker tag` that image ID to the deterministic rollback reference
   `sharipovai:<sha12>`
4. re-verify the OCI revision on the retained tag

Failed-deploy / exact-SHA rollback paths then:

- set `SHARIPOVAI_RELEASE_TAG=<sha12>` so compose selects the retained image
- run `docker compose up -d --remove-orphans --no-build`
- **never** invoke `docker compose build` on the rollback path

Fail closed when:

- the running image ID cannot be resolved
- the OCI revision does not match the expected commit SHA
- the retained rollback artifact is missing
- a tag exists but its OCI revision is wrong (tag alone is not trusted)

Policy helper (unit-tested): `deploy/vps/rollback_image_retention.py`.

## F08 — Exact dependency pins and immutable base digests

- `requirements.txt` uses exact `==` pins on the deploy path.
- Deploy Dockerfiles install those pins and must not run unbound
  `pip install --upgrade pip`.
- Production base images are pinned as **readable tag + immutable digest**:
  - `python:3.12-slim@sha256:…` in `Dockerfile` and `deploy/docker/backend.Dockerfile`
  - `caddy:2-alpine@sha256:…` in `deploy/vps/docker-compose.yml`

### Safe base-image / digest update mechanism

Digest (and readable tag) changes are intentional dependency updates only:

1. Resolve the new multi-arch digest from the registry (e.g. Docker Hub /
   `docker buildx imagetools inspect <image>:<tag>`).
2. Update the `FROM` / `image:` pin in the canonical deploy files above.
3. Keep `requirements.txt` exact pins unless the bump intentionally changes
   Python deps (no mass unrelated upgrades).
4. Run the deploy reproducibility contract tests and CI.
5. Land via PR review — never mutate digests on the VPS by hand.

Floating tags without digests (`python:3.12-slim`, `caddy:2-alpine`) are not
acceptable on the production build path because they can move underfoot.
