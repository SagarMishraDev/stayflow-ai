#!/usr/bin/env bash
#
# Container entrypoint: run pending DB migrations, then start the API.
# Fails loudly if DATABASE_URL is missing or the database is unreachable,
# so a broken migration can never be masked by a silently-running API.
set -euo pipefail

if [ -z "${DATABASE_URL:-}" ]; then
  echo "ERROR: DATABASE_URL is not set — cannot run migrations or start the API." >&2
  exit 1
fi

# `docker compose run --rm api alembic upgrade head` overrides the CMD with an
# explicit alembic invocation — exec it directly instead of migrating twice
# (alembic is idempotent, but the double run is just noise).
if [ "${1:-}" = "alembic" ]; then
  exec "$@"
fi

echo "Running database migrations (alembic upgrade head)..."
alembic upgrade head

echo "Starting API..."
exec "$@"
