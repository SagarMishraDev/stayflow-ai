# syntax=docker/dockerfile:1
#
# StayFlow AI backend — multi-stage build with uv.
#
# Build from the REPO ROOT so the guest web frontend (frontend/, served at
# /chat) is bundled alongside the API:
#   docker build -t stayflow-backend -f backend/Dockerfile .
# (docker-compose.yml already builds with `context: .`.)
#
# Stage 1 (builder): resolve + install locked dependencies into a venv.
# Stage 2 (runtime): slim Python image with the venv and app code only.
# No secrets are baked in: all configuration (DATABASE_URL, tokens, …)
# must come from the environment at container start.
#
# DOCKER CHANGELOG — 2026-09-29 static review (no Docker daemon in this
# sandbox, so the image could not be built here; every claim below was
# verified by inspecting the repo and by simulating container conditions):
# - Build context moved from ./backend to the repo root. The old context
#   could not see ../frontend, so the image silently omitted the guest web
#   chat (app/main.py skips the /chat mount when the directory is absent).
#   The image now COPYs frontend/ to /app/frontend, which is exactly where
#   app/main.py resolves it (parent^3 of app/main.py).
# - `alembic upgrade head` in the entrypoint works because alembic.ini sets
#   `prepend_sys_path = .` and the container WORKDIR is /app/backend
#   (verified: ModuleNotFoundError only when cwd is elsewhere).
# - CMD now passes `--app-dir /app/backend` explicitly. It previously relied
#   on uvicorn's `--app-dir` CLI default ("") quirk to put the cwd on
#   sys.path ("" is not None, so run() inserts it); explicit is robust
#   against future uvicorn default changes. Behaviour is unchanged.
# - docker-entrypoint.sh skips its own migration run when the CMD is already
#   an explicit `alembic ...` invocation, so
#   `docker compose run --rm api alembic upgrade head` no longer runs the
#   migrations twice (alembic is idempotent, but the double run was noise).

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Install dependencies first so this layer is cached across code changes.
COPY backend/pyproject.toml backend/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

# ---------------------------------------------------------------------------

FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/backend/.venv/bin:$PATH"

WORKDIR /app/backend

# Locked venv from the builder stage.
COPY --from=builder /app/.venv /app/backend/.venv

# Application code (alembic env reads settings from the environment).
COPY backend/app ./app
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./
COPY backend/docker-entrypoint.sh ./
# Guest web chat, served at /chat
# (app/main.py resolves this as <repo-root>/frontend -> /app/frontend here).
COPY frontend /app/frontend
RUN chmod +x ./docker-entrypoint.sh

EXPOSE 8000

# The entrypoint runs `alembic upgrade head` first, then execs the CMD.
ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--app-dir", "/app/backend", "--host", "0.0.0.0", "--port", "8000"]
