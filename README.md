# StayFlow AI

> **AI-powered hospitality operations and booking agent** — a FastAPI + PostgreSQL
> PMS-style backend with a deterministic AI agent layer on top.

Guests chat in natural language — on the web, Telegram, or WhatsApp. The AI
agent answers from real hotel data (policies, FAQs, services, rates,
availability, hotel knowledge base) and performs actions (bookings, food
orders, service requests) **only through validated, deterministic tools**.
The LLM never touches the database directly and never decides prices,
availability, or booking state.

```mermaid
flowchart LR
    subgraph Channels
        Web["Web chat (/chat)"]
        TG["Telegram bot"]
        WA["WhatsApp (Twilio)"]
    end
    Web --> Agent
    TG --> Webhooks["Webhook API<br/>/api/v1/webhooks/*"]
    WA --> Webhooks
    Webhooks --> Agent["StayFlow Agent<br/>app/agent/runner.py"]
    Agent --> Mercury["Mercury 2.5<br/>(Inception Labs,<br/>OpenAI-compatible)"]
    Agent --> Tools["Tool registry<br/>18 pydantic-validated tools"]
    Tools --> Services["Service layer<br/>deterministic business rules"]
    Services --> PG[("PostgreSQL<br/>PMS schema")]
    Tools --> RAG["Hotel knowledge RAG<br/>(chunked docs, local embeddings)"]
    RAG --> PG
```

---

## Repository layout

```
stayflow-ai/
├── README.md                  # this file
├── LICENSE                    # MIT
├── docker-compose.yml         # Postgres 16 + API for local Docker stack
├── frontend/                  # guest web chat (vanilla HTML/CSS/JS)
│   ├── index.html
│   ├── styles.css
│   └── app.js                 # talks to POST /api/v1/agent/chat; served at /chat
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI app: staff router, public webhooks,
│   │   │                      # /chat static frontend, /docs
│   │   ├── agent/             # AI agent layer
│   │   │   ├── runner.py      # Understand → Decide → Tool → Respond loop
│   │   │   │                  # (MAX_TOOL_ROUNDS=8 hard cap)
│   │   │   ├── conversation.py# conversation/message persistence
│   │   │   ├── prompts.py     # system prompt (no invented prices/policies)
│   │   │   ├── config.py      # provider selection (mock | ollama | inception)
│   │   │   ├── providers/     # mock, ollama, inception (Mercury 2.5)
│   │   │   └── tools/        # registry + hotel/booking/ops/knowledge tools
│   │   ├── api/
│   │   │   ├── router.py      # staff REST endpoints (JWT-protected) + agent chat
│   │   │   └── webhooks.py    # public Telegram/WhatsApp guest webhooks
│   │   ├── bots/
│   │   │   ├── telegram.py    # Telegram Bot API client + update parsing
│   │   │   └── whatsapp.py    # Twilio client + X-Twilio-Signature verification
│   │   ├── knowledge/         # hotel knowledge RAG
│   │   │   ├── chunking.py    # document → chunks
│   │   │   ├── embeddings.py  # SentenceTransformerEmbedding (default, local)
│   │   │   │                  # + HashedBagOfWordsEmbedding fallback
│   │   │   ├── repository.py  # Postgres storage, hotel_id-scoped reads
│   │   │   └── retriever.py   # top-k cosine retrieval, hotel-isolated
│   │   ├── core/
│   │   │   ├── config.py      # all settings, env-driven (pydantic-settings)
│   │   │   ├── security.py    # argon2 hashing, JWT issue/validate,
│   │   │   │                  # get_current_user (401), require_roles (403)
│   │   │   └── roles.py       # SUPER_ADMIN / HOTEL_ADMIN / STAFF
│   │   ├── services/
│   │   │   ├── booking_service.py  # quotes, availability, booking drafts,
│   │   │   │                       # concurrency locking, negotiation evaluation
│   │   │   └── audit.py       # audit log helper
│   │   ├── models/            # SQLAlchemy 2.0 models (hotels, rooms, rates,
│   │   │                      # availability, guests, bookings, booking drafts,
│   │   │                      # orders, menu, offers, policies, FAQs, services,
│   │   │                      # service requests, negotiation rules, knowledge
│   │   │                      # docs/chunks, conversations, messages,
│   │   │                      # hotel users, audit logs, notifications)
│   │   ├── schemas/           # pydantic request/response schemas
│   │   └── core/config.py     # settings (env-driven)
│   ├── scripts/
│   │   ├── seed_admin.py            # create a hotel's first staff admin (argon2)
│   │   ├── seed_demo.py             # idempotent StayFlow Grand Hotel (Jaipur) demo
│   │   ├── seed_knowledge.py        # seed hotel knowledge-base documents (RAG)
│   │   └── register_telegram_webhook.py  # setWebhook for the Telegram bot
│   ├── alembic/               # database migrations (tz-aware timestamps)
│   ├── tests/                 # 167 automated tests (+2 slow, deselected by default)
│   ├── Dockerfile             # multi-stage build (uv builder → slim runtime)
│   ├── docker-entrypoint.sh   # alembic upgrade head, then uvicorn
│   ├── pyproject.toml
│   └── .env.example
└── .github/workflows/ci.yml   # lint → format → migrate → migrate-check → test
```

---

## Tech stack

| Layer | Technology |
|---|---|
| API | FastAPI (Python 3.12) |
| ORM / migrations | SQLAlchemy 2.0, Alembic |
| Database | PostgreSQL 16 |
| Auth | Staff JWT (HS256, argon2 password hashing via passlib), RBAC |
| Agent LLM providers | Inception Labs Mercury 2.5 (OpenAI-compatible, default-capable), Ollama (local), mock (deterministic, default) |
| Knowledge RAG | `app/knowledge/` — chunking, local hashed-BoW embeddings, Postgres-backed top-k retrieval |
| Messaging | Telegram Bot API webhooks; Twilio WhatsApp webhooks |
| Frontend | Vanilla HTML/CSS/JS, served at `/chat` via `StaticFiles` |
| Packaging / CI | uv, multi-stage Dockerfile, GitHub Actions (ruff + pytest + `alembic check`) |

---

## Quick start

### Prerequisites

- Python 3.12
- [uv](https://docs.astral.sh/uv/) package manager
- PostgreSQL 16 (local instance or Docker)

### 1. Install dependencies

```bash
cd backend
uv sync --locked
```

> Windows (PowerShell): the same commands work in PowerShell. Where an
> instruction below sets an environment variable inline (bash-style
> `VAR=value command`), set it first with `$env:VAR="value"` on its own
> line, then run the command.

### 2. Configure the environment

```bash
cp .env.example .env  # PowerShell: Copy-Item .env.example .env
# edit .env and set DATABASE_URL, e.g.:
# DATABASE_URL=postgresql+psycopg://postgres:Your_Password@localhost:5432/stayflow
```

See [Environment variables](#environment-variables) for the full table.

### 3. Run database migrations

```bash
uv run alembic upgrade head
```

### 4. Seed demo data (optional but recommended)

```bash
# Creates the StayFlow Grand Hotel (Jaipur) demo: hotel, room types, rates,
# availability (90 days), policies, FAQs, offers, services, menu items,
# 5 RAG knowledge documents, and one HOTEL_ADMIN staff user.
# Idempotent — safe to re-run.
SEED_ADMIN_PASSWORD=<redacted> uv run python scripts/seed_demo.py

# Or seed a single staff admin for your own hotel:
uv run python scripts/seed_admin.py --hotel "Grand Plaza" --city Jaipur \
    --name "Asha Admin" --email "admin@grandplaza.example"

# Seed *only* the hotel knowledge base used by RAG (already included in
# seed_demo.py above; use this for pre-existing hotels):
uv run python scripts/seed_knowledge.py --hotel-id 1
```

Knowledge-document embedding follows `EMBEDDING_PROVIDER`
(`sentence-transformer` downloads the ~90 MB `all-MiniLM-L6-v2` model once;
set `EMBEDDING_PROVIDER=hashed` for a fast download-free seed).
Pass `--skip-knowledge` to `seed_demo.py` to skip the RAG documents.

### 5. Start the API

```bash
uv run uvicorn app.main:app --reload --port 8000
```

- Interactive docs: http://localhost:8000/docs
- Guest web chat: http://localhost:8000/chat

### 6. Run the checks

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

---

## Authentication & RBAC

Hotel staff authenticate with `POST /api/v1/auth/login` (email + password →
JWT Bearer token). Passwords are hashed with **argon2**; plaintext is never
stored.

- `get_current_user` validates the JWT (including a role-claim vs. database
  cross-check) → **401** when missing/invalid/expired.
- Staff routes are tenant-scoped: a user can only act on their own hotel's
  data → **403** on cross-hotel access.
- Roles (`app/core/roles.py`): `SUPER_ADMIN` (platform operator; may access
  any hotel — every cross-hotel access is written to the audit log),
  `HOTEL_ADMIN` (manages one hotel incl. staff users), `STAFF` (day-to-day
  operations; cannot manage staff users).
- The Telegram/WhatsApp webhooks and `POST /api/v1/agent/chat` stay public
  (guest surface); they are authenticated by secret-token/signature checks,
  not staff JWTs.

In production the app refuses to start with the development JWT secret —
set a strong random `JWT_SECRET_KEY`.

## Rate limiting

Public-facing endpoints are guarded by an in-memory sliding-window limiter
(`backend/app/core/rate_limit.py`; Redis is not in the stack yet, so each
process enforces its own budget):

| Endpoint | Budget | Keyed by |
|---|---|---|
| `POST /api/v1/agent/chat` | 20 requests / minute | `guest_id` from the request body (client IP when absent) |
| `POST /api/v1/webhooks/telegram/{hotel_id}` | 30 requests / minute | sender identity — Telegram `chat_id` from the update (client IP when absent) |
| `POST /api/v1/webhooks/whatsapp/{hotel_id}` | 30 requests / minute | sender identity — WhatsApp number from the Twilio `From` field (client IP when absent) |
| `POST /api/v1/auth/login` | 5 attempts / minute | client IP + email address (slows credential stuffing without punishing other users) |

When a budget is exhausted the endpoint answers **HTTP 429** with a
`Retry-After` header (seconds until the window resets) and a JSON body like
`{"detail": "Too many requests. Please try again in 42 seconds."}` — the body
and logs never reveal the identity or bucket state. Rate-limit checks run
before request processing but after body validation, so malformed payloads
still get their usual `401` / `403` / `422` answers.

Tune every budget with environment variables (defaults in parentheses):

- `RATE_LIMIT_ENABLED` (`true`) — set to `false` to disable the limiter.
- `RATE_LIMIT_CHAT_PER_MINUTE` (`20`), `RATE_LIMIT_CHAT_WINDOW_SECONDS` (`60`).
- `RATE_LIMIT_WEBHOOK_PER_MINUTE` (`30`), `RATE_LIMIT_WEBHOOK_WINDOW_SECONDS` (`60`).
- `RATE_LIMIT_LOGIN_PER_MINUTE` (`5`), `RATE_LIMIT_LOGIN_WINDOW_SECONDS` (`60`).

---

## AI agent layer

`POST /api/v1/agent/chat`

```json
{
  "hotel_id": 1,
  "message": "Is the Deluxe room available from 2026-10-10 to 2026-10-12?",
  "conversation_id": null,
  "guest_id": null,
  "channel": "web"
}
```

Response includes the guest-facing `reply`, the `conversation_id` (pass it back
for multi-turn context), a `tool_trace` of every tool call, iteration count,
and a `degraded` flag when the provider failed or the loop limit was hit.

### Providers

| Provider | Setting | Notes |
|---|---|---|
| `inception` (default) | `LLM_PROVIDER=inception` | **Inception Labs Mercury 2.5** via its OpenAI-compatible chat-completions API (`INCEPTION_API_KEY`, `INCEPTION_MODEL=mercury-2.5` by default). Requires the key; the app refuses to start without it. |
| `ollama` | `LLM_PROVIDER=ollama` | Local LLM via Ollama. |
| `mock` | `LLM_PROVIDER=mock` (or legacy `AGENT_PROVIDER=mock`) | Deterministic keyword router. **Explicit opt-in for tests and demos only** — never rely on it in production. |

`LLM_PROVIDER` takes precedence when set; otherwise the legacy `AGENT_PROVIDER`
applies, so existing deployments with an explicitly set `AGENT_PROVIDER` keep
working unchanged. The mock provider is never a silent fallback: if the
selected provider is `inception` but `INCEPTION_API_KEY` is missing, the app
fails fast at startup with a clear error.

### Live-tested providers

Honest status of provider verification **in this environment**:

- **Mocked (all verifiable without a key):** the `inception` provider is
  covered against scripted HTTP responses in
  `backend/tests/test_inception_provider.py` (payload building, auth header,
  single/parallel tool-call parsing, malformed tool arguments, 401/403/400
  handling, 429/5xx retry with backoff, timeouts, missing-key fail-fast) and
  `backend/tests/test_provider_hardening.py` (429 budget exhausted, backoff
  timing, registry rejection of hallucinated arguments/unknown tools). All of
  these pass.
- **Live: none in this environment.** No `INCEPTION_API_KEY` was available
  here, so no real call was ever made to `api.inceptionlabs.ai` and no live
  end-to-end conversation has been run. Nothing below is claimed as
  live-verified — the live test still needs to be done by a human with a key.

To run the live end-to-end test yourself:

1. Set your key (never commit it):
   ```powershell
   $env:INCEPTION_API_KEY = "<your-key>"
   ```
   (bash: `export INCEPTION_API_KEY="<your-key>"`)
2. Start the backend from `backend/`:
   ```powershell
   uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```
   The server should log `Agent provider: inception` and start; if the key is
   missing it exits with `Agent provider misconfigured: ...`.
3. Run these scenarios against `POST http://127.0.0.1:8000/api/v1/agent/chat`
   (use a real `hotel_id` from your database), keeping the returned
   `conversation_id` across turns of the same scenario:
   ```powershell
   # Availability (uses seeded rooms/rates)
   Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/agent/chat `
     -ContentType "application/json" `
     -Body '{"hotel_id": 1, "message": "Is the Deluxe room available from 2026-10-10 to 2026-10-12?"}'
   # Price (must come from tool output, not invented)
   # Booking + confirmation gate (preview -> explicit confirm -> create)
   # Negotiation (offer below the rate -> evaluate_price_offer decides)
   # RAG question (spa/restaurant/policy -> search_hotel_knowledge only)
   ```
4. Verify in the responses: prices quoted match tool `tool_trace` results
   exactly; `create_booking` is only ever called after a `preview_booking`
   draft **and** an explicit guest confirmation; the `degraded` flag is
   `false` on the happy path.

### How the agent works

1. **Understand** — the provider (LLM or mock) reads the guest message plus
   the last `AGENT_HISTORY_LIMIT` (default 20) persisted messages.
2. **Decide** — it emits either a final reply or a tool call from the registry
   of **18 tools** (arguments pydantic-validated, all reads hotel-scoped).
3. **Tool** — the handler runs against `booking_service`/the knowledge
   retriever; results feed back into the loop.
4. **Respond** — the loop stops at a final answer or at the hard cap
   `MAX_TOOL_ROUNDS=8` in `app/agent/runner.py` (`AGENT_MAX_ITERATIONS`
   can lower it per call, never raise it). Provider errors and unknown tools
   degrade gracefully instead of crashing.

### The 18 tools

| Group | Tools |
|---|---|
| Hotel info | `list_rooms`, `get_room_details`, `check_room_availability`, `get_room_rate`, `get_hotel_policy`, `search_faq`, `get_services`, `get_offers` |
| Bookings | `find_or_create_guest`, `preview_booking`, `create_booking`, `get_booking`, `cancel_booking`, `evaluate_price_offer` |
| Operations | `get_menu`, `create_food_order`, `create_service_request` |
| Knowledge | `search_hotel_knowledge` |

### Booking architecture — the confirmation gate

Bookings go through a two-phase, deterministic gate; the LLM cannot skip it:

1. `preview_booking` validates dates/capacity/availability, computes the
   total from configured rates, and persists a **`BookingDraft`** with an
   expiry. It books nothing. The agent must present the summary and ask the
   guest to confirm explicitly.
2. `create_booking` (the confirm phase) accepts only a valid, unexpired
   `draft_id`. **Availability and price are re-validated at confirm time** —
   the price is always recomputed from current rates, never taken from the
   LLM or client.

Key business rules (enforced in `app/services/booking_service.py`, never in the LLM):

- Per-night availability with `SELECT … FOR UPDATE` locking (room row locked when
  no date-specific rows exist) — concurrent bookings cannot oversell.
- Bookings can only start as `PENDING`/`CONFIRMED`; status transitions follow a
  fixed state machine; cancelling releases inventory and writes an audit log.
- Guest count ≤ room capacity; availability rows ≤ room inventory; check-out must
  be after check-in.
- Price offers are evaluated against hotel negotiation rules
  (minimum price, max discount %, approval workflow).
- All timestamps are **timezone-aware**.

### Knowledge RAG architecture

`app/knowledge/` powers `search_hotel_knowledge` for **unstructured hotel
knowledge only** (policies, FAQs, spa/restaurant info, area guides):

- `chunking.py` splits seeded documents into chunks; `repository.py` stores
  documents + chunks in Postgres; `retriever.py` does hotel-scoped top-k
  cosine retrieval over indexed `WHERE hotel_id = ?` reads — a second hotel's
  knowledge is never visible.
- Embeddings are **local and offline**: `SentenceTransformerEmbedding`
  (default, `all-MiniLM-L6-v2`, 384-dim) implements the `EmbeddingProvider`
  protocol as a drop-in swap for the previous hashed model. The model
  downloads **once** on first use (~90 MB from Hugging Face into
  `~/.cache/huggingface`, overridable via `HF_HOME`/`HF_HUB_CACHE`) and
  runs fully offline afterwards — no API keys, no network at query time.
  Set `EMBEDDING_PROVIDER=hashed` to fall back to the deterministic
  stdlib-only `HashedBagOfWordsEmbedding` (256-dim; no download — used by
  the unit-test suite), or `EMBEDDING_MODEL=<hf-id>` to pick a different
  local model. `ApiEmbeddingProvider` remains an unwired adapter for a
  future hosted embeddings endpoint.
- **Provider switch = re-ingest**: chunk vectors are stored with the
  provider's dimension (384 for `all-MiniLM-L6-v2`, 256 for `hashed`).
  Changing `EMBEDDING_PROVIDER`/`EMBEDDING_MODEL` on an existing database
  requires re-running `scripts/seed_knowledge.py` (or re-ingesting) so all
  chunks share one dimension — mixed dimensions fail closed in
  `cosine_similarity` instead of returning wrong results.
- **Scope rule (hard):** RAG answers questions about documents. Prices,
  availability, bookings, guest records, and orders always come from the
  deterministic tools/services — never from RAG.

### Background job queue (document ingestion)

Chunking + embedding a document is slow, so ingestion runs in the
background on **Redis + arq** (`backend/app/jobs/`):

- `POST /api/v1/knowledge/documents` (staff JWT, hotel-scoped) persists the
  document with `status: "processing"` and enqueues an `ingest_document`
  job, answering **202 immediately** with the document id. `GET
  /api/v1/knowledge/documents/{id}` (and the list endpoint) expose the
  status for polling; `DELETE /api/v1/knowledge/documents/{id}` removes a
  document and its chunks.
- The worker chunks + embeds the content and flips the document to
  `"ready"`. Any exception flips it to `"failed"` with a one-line `error`
  note (never a traceback) — a failed document stays visible via the API
  and can be re-submitted with a fresh POST.
- **Document status lifecycle:** `processing` → `ready` | `failed`.
  Documents ingested before the queue existed are backfilled to `ready`
  by the migration.

**Running it.** Redis is required (default `REDIS_URL=redis://localhost:6379/0`):

- Locally: start Redis, then run the worker from `backend/` with the venv
  active (same env as the API — `DATABASE_URL`, `REDIS_URL`,
  `EMBEDDING_*`):
  ```bash
  arq app.jobs.queue.WorkerSettings
  ```
  (The worker downloads the sentence-transformer model once on first use,
  like the API.)
- Docker: `docker compose up -d --build` starts a `redis` service and a
  `worker` service (same image as `api`; the entrypoint runs
  `alembic upgrade head` before starting arq). Scale with
  `docker compose up -d --scale worker=2`.
- **No Redis?** Set `INGEST_JOBS_SYNC=true`: the API ingests inline and
  answers 200 with the final status (single-process setups, and what the
  unit tests use). If Redis is unreachable in queue mode, the endpoint
  fails closed with **503** and marks the document `failed`.

### Public web-chat session security

The public `POST /api/v1/agent/chat` endpoint returns an opaque, random
`conversation_token` alongside the numeric conversation id. The web chat stores
that token in `sessionStorage` and sends it on subsequent turns. A caller who
only guesses another conversation's integer id cannot continue or read that
conversation without possessing the token. Telegram and WhatsApp continue to
identify guests through their verified channel identities and use the same
agent/business layer.

For local dashboard development, Vite runs on `http://localhost:5173` and
proxies `/api/*` to the FastAPI server on `http://127.0.0.1:8000`; the example
backend CORS configuration is aligned with that origin.

### Agent safety rails

- **No direct DB access from the LLM** — only the 18 registered tools.
- **Tenant isolation** — every tool call is hotel-scoped; cross-hotel access
  is rejected (super-admin reads are audited).
- **Confirmation gate** — bookings require `preview_booking` →
  explicit guest confirmation → `create_booking` with re-validation.
- **Server-side pricing** — totals are computed from configured rates;
  client/LLM-supplied prices that conflict are rejected.
- **Food orders use menu prices** from the database, never LLM-stated prices.
- **Bounded loop** — hard `MAX_TOOL_ROUNDS=8`; provider errors degrade
  gracefully.
- **Conversation persistence** — every turn (including tool calls/results) is
  stored and replayed as history (bounded by `AGENT_HISTORY_LIMIT`).

---

## Messaging channels

Guest messages from Telegram/WhatsApp flow into the same agent via the public
webhook router (`app/api/webhooks.py`). The guest is matched (or created) by
channel identifier — `telegram_chat_id` / `whatsapp_number` — on
`POST /api/v1/webhooks/{telegram,whatsapp}/{hotel_id}`, and the agent's reply
is sent back through the same channel.

### Telegram setup

1. Create a bot with [@BotFather](https://t.me/BotFather) and set
   `TELEGRAM_BOT_TOKEN` (and a random `TELEGRAM_WEBHOOK_SECRET`) in `.env`.
2. Expose the API publicly (HTTPS required by Telegram), then register the
   webhook for your hotel:
   ```bash
   export TELEGRAM_BOT_TOKEN=<redacted>
   export TELEGRAM_WEBHOOK_SECRET=<redacted>
   export PUBLIC_BASE_URL="https://stayflow.example.com"
   uv run python scripts/register_telegram_webhook.py <HOTEL_ID>
   ```
   This calls `setWebhook` with `secret_token`, so Telegram sends
   `X-Telegram-Bot-Api-Secret-Token` on every update; the webhook endpoint
   rejects requests whose header doesn't match (`POST
   /api/v1/webhooks/telegram/{hotel_id}`).
3. Guests messaging the bot are matched by `telegram_chat_id` and get agent
   replies back in Telegram.

### WhatsApp setup

1. Set up a [Twilio](https://www.twilio.com) account with a WhatsApp sender
   and configure `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, and
   `TWILIO_WHATSAPP_NUMBER` in `.env`.
2. In the Twilio console, point the WhatsApp sandbox/inbox webhook to
   `https://<your-host>/api/v1/webhooks/whatsapp/<HOTEL_ID>`.
3. Every request is verified via the `X-Twilio-Signature` HMAC
   (`app/bots/whatsapp.py::verify_twilio_signature`); invalid signatures are
   rejected before any processing. Guests are matched by `whatsapp_number`
   and get agent replies back in WhatsApp.

---

## Guest web frontend

`frontend/` (vanilla HTML/CSS/JS) is a minimal chat UI that POSTs to
`/api/v1/agent/chat`. The backend serves it at **`/chat`** via
`StaticFiles` (only when the `frontend/` directory exists next to `backend/`).

```bash
uv run uvicorn app.main:app --port 8000
# open http://localhost:8000/chat
```

---

## API overview

| Area | Endpoints |
|---|---|
| Auth | `POST /api/v1/auth/login` |
| Staff users | CRUD `/api/v1/hotel-users` (HOTEL_ADMIN+) |
| Hotels, rooms, guests | CRUD under `/api/v1/hotels`, `/rooms`, `/guests` |
| Hotel rooms (physical) | CRUD `/api/v1/hotel-rooms` |
| Rates / availability | CRUD `/api/v1/rates`, `/api/v1/availability`; unique per room+date |
| Bookings | CRUD `/api/v1/bookings`, plus `POST /bookings/quote`, `GET /bookings/availability-check`, `POST /bookings/{id}/cancel` |
| Negotiation | CRUD `/api/v1/negotiation-rules`, `POST /api/v1/negotiation/evaluate` |
| Orders / menu | CRUD `/api/v1/orders`, `/api/v1/menu-items`, `/api/v1/order-items` |
| Services | CRUD `/api/v1/services`, `/api/v1/service-requests` |
| Knowledge base | CRUD `/api/v1/knowledge/documents` (staff JWT, hotel-scoped; ingestion runs in the arq worker, `POST` answers 202); the agent reads through the `search_hotel_knowledge` tool |
| Conversations | `POST /api/v1/conversations`, message post/list |
| Agent | `POST /api/v1/agent/chat` |
| Webhooks (public) | `POST /api/v1/webhooks/telegram/{hotel_id}`, `POST /api/v1/webhooks/whatsapp/{hotel_id}` |
| System | `GET /api/v1/audit-logs`, `GET /api/v1/notifications`, `PATCH /api/v1/notifications/{id}/read` |

Only `/health`, `POST /api/v1/agent/chat`, and the two webhook routes are
reachable without a staff JWT; every other route requires a valid token and
enforces hotel-level tenant isolation.

---

## Environment variables

Every setting the code reads (see `backend/app/core/config.py`) is listed in
`backend/.env.example`. Full table:

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | *(required)* | PostgreSQL URL, psycopg v3 driver |
| `ENVIRONMENT` | `development` | `production` enforces all required secrets (see Production secrets checklist) |
| `DEBUG` | `false` | Debug mode |
| `APP_NAME` / `APP_VERSION` | `StayFlow AI` / `0.1.0` | Metadata |
| `API_PREFIX` | `/api/v1` | Route prefix |
| `ALLOWED_ORIGINS` | `["http://localhost:3000"]` | CORS origins (tighten in prod) |
| `LOG_LEVEL` | `INFO` | Logging level |
| `JWT_SECRET_KEY` | dev-only default | Signs staff JWTs — **must be set in production** |
| `JWT_ALGORITHM` | `HS256` | JWT signing algorithm |
| `JWT_EXPIRE_MINUTES` | `480` | Staff session lifetime (minutes) |
| `LLM_PROVIDER` | *(unset)* | `inception` \| `ollama` \| `mock`; takes precedence over `AGENT_PROVIDER`; production default is `inception` |
| `AGENT_PROVIDER` | `inception` | Legacy provider selector, same values |
| `AGENT_MODEL` | `qwen3:8b` | Ollama model when provider is `ollama` |
| `AGENT_OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama endpoint |
| `AGENT_TIMEOUT_SECONDS` | `120` | LLM call timeout |
| `AGENT_TEMPERATURE` | `0.2` | LLM temperature |
| `AGENT_MAX_ITERATIONS` | `8` | Soft loop cap (hard cap `MAX_TOOL_ROUNDS=8` always wins) |
| `AGENT_HISTORY_LIMIT` | `20` | Max persisted messages replayed as history |
| `INCEPTION_API_KEY` | *(unset)* | Inception Labs API key (never logged) |
| `INCEPTION_MODEL` | `mercury-2.5` | Mercury model name |
| `INCEPTION_BASE_URL` | `https://api.inceptionlabs.ai/v1` | OpenAI-compatible endpoint |
| `INCEPTION_TIMEOUT_SECONDS` | `120` | Inception call timeout |
| `INCEPTION_MAX_RETRIES` | `2` | Retries on retryable errors (429/5xx) |
| `EMBEDDING_PROVIDER` | `sentence-transformer` | Knowledge RAG embedding backend: `sentence-transformer` (local semantic model) or `hashed` (stdlib-only fallback, no download) |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Local sentence-transformer model id (Hugging Face); downloaded once (~90 MB), then runs offline |
| `TELEGRAM_BOT_TOKEN` | *(unset)* | Bot token from @BotFather |
| `TELEGRAM_WEBHOOK_SECRET` | *(unset)* | Verified via `X-Telegram-Bot-Api-Secret-Token` |
| `TWILIO_ACCOUNT_SID` | *(unset)* | Twilio account SID |
| `TWILIO_AUTH_TOKEN` | *(unset)* | Twilio auth token (used for signature verification) |
| `TWILIO_WHATSAPP_NUMBER` | *(unset)* | WhatsApp sender, e.g. `whatsapp:+14155238886` |
| `RATE_LIMIT_ENABLED` | `true` | `false` disables the public-endpoint rate limiter |
| `RATE_LIMIT_CHAT_PER_MINUTE` / `RATE_LIMIT_CHAT_WINDOW_SECONDS` | `20` / `60` | `POST /api/v1/agent/chat` budget, keyed by `guest_id` (IP fallback) |
| `RATE_LIMIT_WEBHOOK_PER_MINUTE` / `RATE_LIMIT_WEBHOOK_WINDOW_SECONDS` | `30` / `60` | Telegram/WhatsApp webhook budget, keyed by sender identity (IP fallback) |
| `RATE_LIMIT_LOGIN_PER_MINUTE` / `RATE_LIMIT_LOGIN_WINDOW_SECONDS` | `5` / `60` | `POST /api/v1/auth/login` budget, keyed by client IP + email |

### Production secrets checklist

Copy `backend/.env.production.example` to `.env` on the production host and
fill in real values — never commit a real `.env`. Generate strong random
secrets with `openssl rand -hex 32`.

Fail-fast behavior (`backend/app/core/config.py`, `_require_prod_secrets`):
when `ENVIRONMENT=production`, the app **refuses to start** if any required
secret is missing/blank or left at its insecure dev default:

- `JWT_SECRET_KEY` — must differ from the built-in dev default.
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET` — must both be set.
- `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` — must both be set.
- `DATABASE_URL` — already required in every environment; in production a
  local `sqlite` URL is additionally rejected.
- `INCEPTION_API_KEY` — required only when the active LLM provider is
  `inception` (`mock`/`ollama` deployments don't need it).

The startup error names each offending variable and how to fix it, without
echoing secret values. Non-production environments (`development`, `test`)
are unaffected and keep working with the dev defaults.

---

## Database setup & migrations

```bash
cd backend
uv run alembic upgrade head      # apply all migrations
uv run alembic check             # fail if models drifted from migrations
```

All timestamps are timezone-aware (`DateTime(timezone=True)`, migration
`cedfb3d5506c`). Downgrading old (pre-existing) migrations is not fully
supported; forward migrations are verified.

---

## Testing

**173 tests across 17 files** (+2 `slow` tests deselected by default — they
download and load the real `all-MiniLM-L6-v2` sentence-transformer model;
run them explicitly with `pytest -m slow`), all hitting a real PostgreSQL
database:

```bash
# test DB (see .github/workflows/ci.yml for CI parity)
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/stayflow_test \
AGENT_PROVIDER=mock \
uv run pytest
```

PowerShell:

```powershell
$env:DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:5432/stayflow_test"
$env:AGENT_PROVIDER="mock"
uv run pytest
```

| File | Covers |
|---|---|
| `test_pms_api.py`, `test_pms_comprehensive.py`, `test_database.py`, `test_health.py` | Original PMS suite, schema, health |
| `test_booking_rules.py` | Quotes, server-side pricing, sold-out, capacity, cancellation/inventory release, status machine, duplicate rate/availability → 409, negotiation limits, cross-hotel FK validation, concurrent-booking oversell guard |
| `test_agent.py` | Mock chat flows (availability, price, policy, FAQ, booking confirmation gate, cancellation, sold-out), conversation persistence + cross-guest isolation, tool validation, tenant isolation, menu-price enforcement, loop-limit and provider-failure degradation |
| `test_prompt_injection.py` | Simulated compromised LLM: system-prompt/secret non-disclosure, cross-hotel tool calls rejected, smuggled price args rejected, booking without a draft creates nothing, price-change re-confirmation, conversation-id swap isolation |
| `test_auth.py` | Login, JWT validation, 401 on bad/missing token |
| `test_audit_trail.py` | Audit rows written for auth login/login-failed, offer create/modify/delete, order + order-item mutations, service-request modify/delete |
| `test_rbac.py` | Role enforcement, 403 cross-hotel, super-admin audited access |
| `test_webhooks.py` | Telegram secret-token verification, Twilio signature verification, guest mapping |
| `test_rate_limit.py` | 429 + Retry-After on chat/webhook/login budgets, per-identity buckets |
| `test_jobs.py` | arq document-ingestion queue (enqueue → worker → ready), sync fallback |
| `test_inception_provider.py` | Inception payload building, tool-call parsing, retries, error mapping (scripted HTTP; no live API calls) |
| `test_config_security.py` | Production secrets fail-fast validation (refuses to start with missing/insecure secrets) |
| `test_provider_hardening.py` | Registry rejection of hallucinated/unknown/malformed tool args, 429-exhausted surfacing, retry backoff, provider-failure degradation, inception default + missing-key fail-fast |
| `test_rag.py` | Chunking, embedding, hotel-isolated retrieval, non-`ready` documents excluded; `slow`-marked tests exercise the real `all-MiniLM-L6-v2` model (`pytest -m slow`) |

---

## CI

`.github/workflows/ci.yml` (runs on `main`/`develop` pushes and PRs):

1. Postgres 16 service container (`stayflow_test` DB)
2. `uv sync --locked`
3. `ruff check .` and `ruff format --check .`
4. `alembic upgrade head`
5. **`alembic check`** — fails if the models have drifted from the migrations
6. `pytest` against the service Postgres

---

## Deployment notes

- Run `alembic upgrade head` on every deploy (CI does this).
- **Docker:** the API ships as a multi-stage image — see
  `backend/Dockerfile` (locked `uv sync` build, slim runtime,
  `backend/docker-entrypoint.sh` runs `alembic upgrade head` before
  starting uvicorn, so migrations apply automatically on container
  start). **Build from the repo root** — the build context is `.`, so the
  guest web chat (`frontend/`, served at `/chat`) is bundled into the
  image: `docker build -t stayflow-backend -f backend/Dockerfile .`
  (a DOCKER CHANGELOG at the top of the Dockerfile documents the
  2026-09-29 static-review fixes). For a full local stack:
  `docker compose up -d --build` (see `docker-compose.yml`: Postgres 16,
  Redis 7 for the arq job queue, the API, and an arq `worker` service with
  `pgdata`/`redisdata` named volumes; DB credentials, `DATABASE_URL`, and
  `REDIS_URL` come from a repo-root `.env` — `cp backend/.env.example .env`
  — with dev defaults). Migrations can also be run one-off without starting the
  server: `docker compose run --rm api alembic upgrade head`
  (the entrypoint detects this and does not migrate twice). No secrets
  are baked into the image; all config comes from the environment.
- Set `ENVIRONMENT=production`, `DEBUG=false`, and a restrictive
  `ALLOWED_ORIGINS` in `.env` (use `backend/.env.production.example` as the
  template — the app refuses to start in production with missing secrets).
- Serve behind HTTPS with a process manager (systemd/supervisor) or a
  container; `uvicorn app.main:app --workers 4` for production.
- Back up PostgreSQL regularly; the audit log is append-only by convention.
- Licensed under the **MIT License** (`LICENSE`).

## Troubleshooting

| Symptom | Fix |
|---|---|
| `database_url: Field required` | `DATABASE_URL` is not set — copy `.env.example` to `.env`. |
| `409` on rate/availability create | A row already exists for that room+date — `PATCH` it instead. |
| `422` "No availability" on booking | Some night in the range is sold out — check `/bookings/availability-check`. |
| `422` price mismatch on booking | A client-supplied `final_price` must equal the server-computed total. |
| Agent says "too many steps" | The loop hit `MAX_TOOL_ROUNDS`; rephrase more simply or switch provider. |
| Agent chat slow/hanging with ollama | Check Ollama is running (`ollama list`) and lower `AGENT_TIMEOUT_SECONDS`. |
| App refuses to start in production | `JWT_SECRET_KEY` is still the dev default — set a strong random value. |
| Telegram webhook 401 | `TELEGRAM_WEBHOOK_SECRET` doesn't match the `secret_token` registered via `setWebhook`. |

## Known limitations

- **Mercury 2.5 has not been live-tested** — no Inception API key exists in
  this environment; only scripted (mocked-HTTP) provider tests exist.
  The mock provider is the verifiable default; real conversation quality
  needs Mercury or the Ollama provider with a capable tool-calling model.
- **Embeddings need a one-time model download**: the default
  `SentenceTransformerEmbedding` (`all-MiniLM-L6-v2`, ~90 MB) downloads from
  Hugging Face on first use and is cached locally
  (`~/.cache/huggingface`); inference afterwards is fully offline. The
  unit-test suite pins `EMBEDDING_PROVIDER=hashed` (stdlib-only, no
  download); the real-model integration tests are marked `slow` and skipped
  by default — run them with `pytest -m slow`.
- **Docker stack was not verified in this sandbox** — there is no Docker
  daemon here (`docker: command not found`, confirmed 2026-09-29), so the
  image was never built and `docker compose up` was never run in this
  environment. The Dockerfile, entrypoint, and compose file were statically
  reviewed and fixed on 2026-09-29 (see the DOCKER CHANGELOG at the top of
  `backend/Dockerfile`), but that is not a substitute for a real build.
  To verify locally, run these from the repo root (note: the health
  endpoint lives at `/api/v1/health`, and the build context is the repo
  root, not `./backend`):
  ```bash
  docker build -t stayflow-backend -f backend/Dockerfile .
  docker compose up -d --build
  docker compose ps
  curl http://localhost:8000/api/v1/health
  # expect {"status":"ok","service":"StayFlow AI","version":"0.1.0"}
  curl -s http://localhost:8000/chat | head -c 120  # guest web chat is bundled
  # restart persistence (migrations re-run, API comes back):
  docker compose restart api && curl http://localhost:8000/api/v1/health
  # data persistence across a full stack recreate (pgdata named volume):
  docker compose down && docker compose up -d && curl http://localhost:8000/api/v1/health
  ```
- No Kubernetes manifests or production hardening (rate limiting, WAF,
  secret rotation) — out of scope for this phase.
- Downgrading old (pre-existing) migrations is not fully supported; forward
  migrations are verified.
- Single-language (English) system prompt.
