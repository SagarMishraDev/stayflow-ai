"""StayFlow AI — single-service DEMO application wrapper.

This module wraps the real application (``app.main:app``) so the entire
product can be served from ONE FastAPI process on ONE port, for a public
demo deployment (see ``Dockerfile.demo`` / ``render.yaml`` at the repo
root and ``docs/DEMO_DEPLOY.md``):

- ``/``                 hotel landing page — with
                        ``window.STAYFLOW_DASHBOARD_URL = "/dashboard/"``
                        injected by THIS wrapper only (the committed
                        landing files are never edited for the demo)
- ``/chat``             guest chat            (from app.main)
- ``/widget``, ``/widget.js``  embeddable widget (from app.main)
- ``/api/v1/*``         REST + agent + public APIs (from app.main)
- ``/dashboard/``       staff dashboard SPA, built with
                        ``VITE_BASE=/dashboard/ npm run build:demo``
                        (output: ``frontend/dashboard/dist-demo``) with
                        SPA fallback to its ``index.html``

Nothing here changes the real app: importing ``app.main`` registers all
of its routes/mounts first; this wrapper only (a) replaces the ``GET /``
landing route with an injecting variant, and (b) appends the
``/dashboard`` routes. No other path is touched, so /api, /docs, /chat,
/widget and /landing keep their original handlers.

Demo seeding: when ``DEMO_SEED=1`` is set in the environment, startup
(this module's import, which happens before uvicorn serves requests)
prepares the database via ``app.demo_bootstrap``: on PostgreSQL (the
live demo, on Neon) it runs the Alembic migrations to head in-process;
on SQLite (local throwaway runs) it keeps the ``create_all`` shortcut.
Either way, if the hotels table is empty it then runs
``scripts/seed_demo.py`` with ``SEED_ADMIN_PASSWORD`` (default
``Preview@123``, a DEMO-ONLY password that is printed in the deploy
docs; it is not a real credential).

Run locally::

    DEMO_SEED=1 DATABASE_URL=sqlite:////tmp/demo.db LLM_PROVIDER=mock \
    EMBEDDING_PROVIDER=hashed \
        uvicorn app.demo_main:app --port 9000
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from app.main import app  # noqa: F401  (re-exported as the ASGI app)

logger = logging.getLogger(__name__)

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _BACKEND_DIR.parent
_LANDING_INDEX = _REPO_ROOT / "frontend" / "landing" / "index.html"
_DASHBOARD_DIST = _REPO_ROOT / "frontend" / "dashboard" / "dist-demo"

_DASHBOARD_URL = "/dashboard/"
_INJECT = f'<script>window.STAYFLOW_DASHBOARD_URL = "{_DASHBOARD_URL}";</script>'


# --------------------------------------------------------------------------
# Demo seeding (DEMO_SEED=1)
# --------------------------------------------------------------------------
def _seed_demo_if_empty() -> None:
    """Prepare and seed the demo database when DEMO_SEED=1.

    Delegates to ``app.demo_bootstrap.prepare_demo_database``:
    PostgreSQL (the live Neon demo) is migrated to Alembic head;
    SQLite (local throwaway runs) uses ``create_all``. Both shapes
    seed only when the hotels table is empty, and migration failures
    raise — startup must fail loudly rather than serve a
    half-migrated database.
    """
    if os.environ.get("DEMO_SEED") != "1":
        return

    from app.core.config import get_settings
    from app.demo_bootstrap import prepare_demo_database

    prepare_demo_database(get_settings().database_url)


_seed_demo_if_empty()


# --------------------------------------------------------------------------
# Landing page at "/" with the dashboard URL injected (wrapper only)
# --------------------------------------------------------------------------
# app.main registered a plain FileResponse route for GET /. Replace it so
# the demo build can point the landing page's staff-login redirect at the
# same-origin dashboard. Only the exact root route is removed.
app.router.routes[:] = [
    route
    for route in app.router.routes
    if not (
        getattr(route, "path", None) == "/" and "GET" in (getattr(route, "methods", None) or set())
    )
]


@app.get("/", include_in_schema=False)
async def _demo_landing_root() -> HTMLResponse:
    html = _LANDING_INDEX.read_text(encoding="utf-8")
    if "</head>" in html:
        html = html.replace("</head>", f"    {_INJECT}\n  </head>", 1)
    else:  # pragma: no cover - landing index always has a head
        html = _INJECT + html
    return HTMLResponse(html)


# --------------------------------------------------------------------------
# Staff dashboard SPA at /dashboard/ (built to frontend/dashboard/dist-demo)
# --------------------------------------------------------------------------
@app.get("/dashboard", include_in_schema=False)
async def _dashboard_bare() -> RedirectResponse:
    return RedirectResponse(url=_DASHBOARD_URL)


@app.get("/dashboard/{full_path:path}", include_in_schema=False)
async def _dashboard_spa(full_path: str) -> FileResponse:
    """Serve dashboard build assets; unknown subpaths fall back to the SPA
    index so React Router can handle /dashboard/login, /dashboard/orders…
    """
    candidate = (_DASHBOARD_DIST / full_path).resolve()
    if full_path and candidate.is_file() and candidate.is_relative_to(_DASHBOARD_DIST.resolve()):
        return FileResponse(candidate)
    return FileResponse(_DASHBOARD_DIST / "index.html", media_type="text/html")
