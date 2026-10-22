# StayFlow AI — Public Demo Deployment (single service)

One container, one port, everything served by one FastAPI process
(`backend/app/demo_main.py`, a thin wrapper around the real
`app.main:app` — the production app, Dockerfile and docker-compose are
untouched).

| Path | What |
|---|---|
| `/` | Hotel landing page (wrapper injects `window.STAYFLOW_DASHBOARD_URL = "/dashboard/"`) |
| `/chat` | Guest chat |
| `/widget`, `/widget.js` | Embeddable widget |
| `/api/v1/*` | REST + agent + public APIs |
| `/dashboard/` | Staff dashboard SPA (SPA fallback to its index) |

The deployed demo runs the **real stack**: the Mercury LLM (Inception
Labs) as the agent provider and a persistent **Neon PostgreSQL**
database. The mock provider + throwaway SQLite remain available for
local offline runs only.

## How it works

- **Dashboard subpath build:** `frontend/dashboard` builds normally with
  base `/`. The demo build — `VITE_BASE=/dashboard/ npm run build:demo`
  (script in `package.json`, output `frontend/dashboard/dist-demo`) —
  makes Vite emit asset URLs under `/dashboard/` and React Router uses
  `import.meta.env.BASE_URL` as its basename, so the same source works
  at both bases. The axios API base stays the absolute `/api/v1`, so the
  dashboard talks to the same-origin API with no proxy.
- **Demo wrapper:** `app/demo_main.py` imports the real app, replaces
  only the `GET /` route (injecting the dashboard URL into the landing
  HTML in-memory — the committed landing files are never edited), and
  adds `/dashboard` routes that serve `dist-demo` files with SPA
  fallback.
- **First-boot database setup:** with `DEMO_SEED=1`, importing the
  wrapper prepares the database via `app/demo_bootstrap.py` *before*
  uvicorn serves anything:
  - **PostgreSQL** (the live demo): Alembic migrations run to head
    **in-process**, then — only if the hotels table is empty —
    `scripts/seed_demo.py` loads the demo hotel. A migration failure
    aborts startup loudly; a half-migrated database never serves.
    Reboots against the migrated, seeded database are no-ops.
  - **SQLite** (local throwaway runs): `create_all` shortcut, then the
    same seed-if-empty.
  The seeded admin is `admin@stayflowgrand.example` with the password
  from `SEED_ADMIN_PASSWORD` (demo default in `render.yaml`:
  `Preview@123` — **demo-only, on demo data; not a real credential**).
- **DATABASE_URL normalization:** Neon hands out bare
  `postgresql://…?sslmode=require` URLs. `Settings` rewrites them to
  `postgresql+psycopg://` (the psycopg v3 driver this project ships) in
  exactly one place (`app/core/config.py: normalize_database_url`), so
  the app engine, the Alembic env and the demo bootstrap all see the
  same URL.

## Secrets (dashboard-only, never in git)

`render.yaml` declares both secrets with `sync: false` — values are set
in the Render dashboard and never committed:

| Variable | Value |
|---|---|
| `DATABASE_URL` | Neon **direct** connection string (see below) |
| `INCEPTION_API_KEY` | Inception Labs (Mercury) API key |

Without `INCEPTION_API_KEY` the app refuses to start (fail-fast
provider validation in `app/main.py`) — set both variables *before*
triggering the redeploy that flips the providers to `inception`.

## Neon setup (one-time)

1. On [neon.tech](https://neon.tech): create a free account and a new
   project (any name, e.g. `stayflow-ai`; default Postgres version).
2. In the project, open **Connect / Connection Details**.
3. Switch **Connection pooling OFF** and copy the **direct** connection
   string — it looks like
   `postgresql://<user>:<password>@<host>/<db>?sslmode=require`
   (not the `-pooler` host; the app is a single small service and uses
   the direct endpoint).
4. On Render: `stayflow-ai-demo` → **Environment** → set `DATABASE_URL`
   to that string, and `INCEPTION_API_KEY` to the Mercury key from the
   Inception Labs dashboard. Save → the service redeploys.
5. First boot against the empty Neon database runs the migrations and
   the seed automatically (watch for `DEMO_SEED: migrations complete`
   and `DEMO_SEED: seed complete` in the Render logs). Log in from the
   landing page's Staff Login (or `/dashboard/`) with the demo admin
   above.

After that, **data persists across restarts and redeploys** — Neon is a
durable database, unlike the old ephemeral SQLite file. Two free-tier
behaviours remain: the Render app still **spins down when idle** (first
hit after a nap is slow), and Neon **scales to zero** when idle and
wakes automatically on the first connection (about a second) — neither
loses data.

`ENVIRONMENT=demo` is deliberate: `production` mode (correctly) refuses
to boot without the full production secret set (Telegram/Twilio …);
see the comment in `render.yaml`.

## Telegram bot (optional, paste-only activation)

The demo can also serve guests on Telegram: the same agent, the same
booking tools, over the Bot API. The webhook route and connector have
always been in the app — activation is three pastes, no code change:

1. In Telegram, open **@BotFather** → `/newbot` → pick a name and a
   username for the bot. BotFather replies with the bot **token**.
2. Generate a webhook secret, e.g. `openssl rand -hex 32`.
3. On Render: `stayflow-ai-demo` → **Environment** → set
   `TELEGRAM_BOT_TOKEN` (the BotFather token) and
   `TELEGRAM_WEBHOOK_SECRET` (the random string). `APP_PUBLIC_BASE_URL`
   is already set in `render.yaml` to the service's public URL. Save —
   the service redeploys.
4. On startup the app registers the webhook itself
   (`setWebhook` → `{APP_PUBLIC_BASE_URL}/api/v1/webhooks/telegram/{hotel_id}`,
   with the secret as Telegram's `secret_token`, which the webhook
   route verifies on every update). Watch the Render logs for
   `Telegram webhook registered: …`. Registration is idempotent and
   failure-tolerant: if Telegram is unreachable the app logs a warning
   and boots anyway — the website is never held hostage by the bot.

Notes:

- One bot token = one webhook URL, and the webhook path is per-hotel,
  so the bot serves the (single) demo hotel; a multi-hotel deployment
  gives each hotel its own bot.
- To test: open the bot in Telegram and message it like a guest —
  "Hi, do you have a pool?", "I want a room from 23/11 to 25/11" — the
  reply comes from the same Mercury agent as the website chat, and the
  conversation appears in the staff dashboard.
- To switch the bot off again, clear `TELEGRAM_BOT_TOKEN` in the
  dashboard and redeploy; with no token the startup hook does nothing.
- `scripts/register_telegram_webhook.py` remains available for manual
  registration (e.g. pointing a bot at a local tunnel while developing).

## Run the same image locally

```bash
docker build -f Dockerfile.demo -t stayflow-demo .
cp .env.demo.example .env.demo   # paste the real Neon URL + Mercury key
docker run --rm -p 8000:8000 --env-file .env.demo stayflow-demo
# → http://localhost:8000/  (landing)  ·  /dashboard/  ·  /chat
```

Without Docker, the wrapper runs directly. This offline variant uses
the mock provider + throwaway SQLite (no key, no network database):

```bash
cd frontend/dashboard && VITE_BASE=/dashboard/ npm run build:demo && cd ../..
cd backend && DEMO_SEED=1 DATABASE_URL=sqlite:////tmp/demo.db \
  LLM_PROVIDER=mock EMBEDDING_PROVIDER=hashed \
  uvicorn app.demo_main:app --port 9000
```
