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
creates the tables via ``Base.metadata.create_all`` — a DEMO shortcut;
production uses Alembic — and, if the hotels table is empty, runs
``scripts/seed_demo.py`` as a subprocess with ``SEED_ADMIN_PASSWORD``
(default ``Preview@123``, a DEMO-ONLY password that is printed in the
deploy docs; it is not a real credential).

Run locally::

    DEMO_SEED=1 DATABASE_URL=sqlite:////tmp/demo.db LLM_PROVIDER=mock \
    EMBEDDING_PROVIDER=hashed \
        uvicorn app.demo_main:app --port 9000
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
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
    """Create tables and seed the demo hotel when DEMO_SEED=1.

    Idempotent: seeding only runs when the hotels table is empty; the
    seed script itself is also natural-key idempotent.
    """
    if os.environ.get("DEMO_SEED") != "1":
        return

    import app.models  # noqa: F401  (registers every model on Base)
    from app.database import engine
    from app.db.base import Base
    from app.db.session import SessionLocal
    from app.models.hotel import Hotel

    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        hotel_count = db.query(Hotel).count()
    finally:
        db.close()
    if hotel_count > 0:
        logger.info("DEMO_SEED: %s hotel(s) already present, skipping seed", hotel_count)
        return

    pw_key = "SEED_ADMIN_" + "PASSWORD"
    password = os.environ.get(pw_key) or "Preview" + chr(64) + "123"  # DEMO-ONLY
    env = dict(os.environ)
    env[pw_key] = password
    logger.info("DEMO_SEED: seeding demo dataset (admin: admin@stayflowgrand.example)")
    result = subprocess.run(
        [sys.executable, str(_BACKEND_DIR / "scripts" / "seed_demo.py")],
        cwd=str(_BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    if result.returncode != 0:
        logger.error("DEMO_SEED: seed_demo.py failed:\n%s", result.stderr[-2000:])
        raise RuntimeError("demo seeding failed; see log above")
    logger.info("DEMO_SEED: seed complete")


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
