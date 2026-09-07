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
# Transactional runtime ownership

Production may belong to a `sharipovai-runtime-*` Compose project while its data
volume and Caddy network retain their original names. `runtime_compose_context.py`
captures that actual project, named data volume and shared proxy network before
checkout changes. It verifies the running image ID, image revision, embedded build
SHA and every execution lock. Its output contains only resource names and Compose
structure, never runtime environment values.

The updater and exact-SHA rollback retain this context through failure recovery.
They operate only on the application service with `--no-deps --no-build` during
replacement/recovery; Caddy and unrelated project resources are not reconciled.
Image retention precedes checkout mutation. A dirty checkout or unproven runtime
identity blocks the operation. Health requires the Docker healthcheck and HTTP
probe to pass within the existing bounded retry window.

Rollback to a commit predating the context helper is supported because the context
is captured before resetting the checkout. The retained image remains the rollback
artifact; it is never rebuilt. This changes no database schema or execution authority.

For the first rollout from an older checkout, fetch and review an immutable target
commit, then materialize its `deploy/vps/update_from_main.sh` using `git show` into
a private temporary file and validate it with `bash -n`. Run that target updater
with `SHARIPOVAI_EXPECTED_TARGET_SHA` set to the exact CI-approved commit. It loads
and compile-validates the helper from the same target before any checkout reset;
the old checkout does not need to contain the helper. The current Docker and HTTP
health, complete safety locks, and image retention are checked before the target
preflight and exporter. The checkout and runtime identity are rechecked immediately
before mutation. After startup and recovery, the immutable helper verifies image
provenance and confirms that project, external data volume and proxy network still
match the captured context.

Regression coverage executes the updater against a disposable Git remote with an
old commit lacking the helper, and uses strict Docker/HTTP fakes. It covers target
bootstrap, candidate health failure, volume drift, retained-image rollback, unsafe
target flags, HTTP failure, invalid helper syntax and a changed release SHA. Live
backup/isolated restore acceptance and exact main CI remain separate rollout gates.
