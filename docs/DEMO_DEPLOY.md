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
- **Seeding:** with `DEMO_SEED=1`, importing the wrapper creates tables
  (`create_all` — a demo shortcut; production uses Alembic) and, if the
  hotels table is empty, runs `scripts/seed_demo.py`. The seeded admin
  is `admin@stayflowgrand.example` with the password from
  `SEED_ADMIN_PASSWORD` (demo default in `render.yaml`: `Preview@123` —
  **demo-only, on throwaway demo data; not a real credential**).

## Deploy on Render (remaining steps — need Sagar's logins)

1. Push this repo (including `Dockerfile.demo` + `render.yaml`) to
   GitHub — *not done by the agent; no commit/push was made.*
2. On render.com: **New → Blueprint**, connect the GitHub repo, select
   the branch. Render reads `render.yaml` and creates the free
   `stayflow-ai-demo` web service using `Dockerfile.demo` (the dashboard
   is built inside the image by the Node stage — no local prebuild
   needed).
3. Wait for the first deploy; open the service URL. First boot seeds
   the demo hotel automatically. Log in from the landing page's Staff
   Login (or `/dashboard/`) with the demo admin above.
4. Notes: the free plan sleeps when idle (first hit is slow) and its
   filesystem is ephemeral — the SQLite demo DB is re-seeded on every
   fresh boot, which is fine for a demo. `ENVIRONMENT=demo` is
   deliberate: `production` mode (correctly) refuses SQLite and demands
   production secrets; see the comment in `render.yaml`.

## Run the same image locally

```bash
docker build -f Dockerfile.demo -t stayflow-demo .
cp .env.demo.example .env.demo   # fill in any random JWT secret
docker run --rm -p 8000:8000 --env-file .env.demo stayflow-demo
# → http://localhost:8000/  (landing)  ·  /dashboard/  ·  /chat
```

Without Docker, the wrapper runs directly:

```bash
cd frontend/dashboard && VITE_BASE=/dashboard/ npm run build:demo && cd ../..
cd backend && DEMO_SEED=1 DATABASE_URL=sqlite:////tmp/demo.db \
  LLM_PROVIDER=mock EMBEDDING_PROVIDER=hashed \
  uvicorn app.demo_main:app --port 9000
```
