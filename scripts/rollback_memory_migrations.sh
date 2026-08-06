#!/usr/bin/env bash
set -euo pipefail

if [[ "${MEMORY_ENABLED:-false}" =~ ^(1|true|yes|on)$ ]]; then
  echo "Refusing rollback while MEMORY_ENABLED is true" >&2
  exit 2
fi

exec python scripts/rollback_memory_migrations.py "$@"
