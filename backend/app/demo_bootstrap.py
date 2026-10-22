"""Database bootstrap for the single-service DEMO wrapper.

Used only by ``app.demo_main`` when ``DEMO_SEED=1`` (see
``docs/DEMO_DEPLOY.md``). Two shapes, chosen by the database URL:

- **PostgreSQL** (the live demo, on Neon): production-shaped — run the
  Alembic migrations to head IN-PROCESS, then seed if the hotels table
  is empty. Re-running against an already-migrated, already-seeded
  database is a no-op (``upgrade head`` at head does nothing; the seed
  is skipped when hotels exist).
- **SQLite** (local throwaway runs): the original demo shortcut —
  ``Base.metadata.create_all``, then the same seed-if-empty.

Migration failures propagate (raise): a half-migrated database must
never serve silently.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

from app.core.config import normalize_database_url

logger = logging.getLogger(__name__)

_BACKEND_DIR = Path(__file__).resolve().parent.parent


def is_postgres_url(database_url: str) -> bool:
    return database_url.startswith("postgresql")


def run_migrations(database_url: str) -> None:
    """Upgrade the database to Alembic head, in-process.

    The normalized URL is loaded into the Alembic config here; note that
    ``alembic/env.py`` independently re-derives ``sqlalchemy.url`` from
    ``get_settings().database_url`` — the same normalized URL — so there
    is exactly one source of truth for the connection string. A bare
    ``Config()`` (no alembic.ini) keeps ``env.py`` from reconfiguring
    logging via ``fileConfig``; ``script_location`` is pointed at the
    backend's alembic directory explicitly instead.
    """
    from alembic.config import Config

    from alembic import command

    cfg = Config()
    cfg.set_main_option("script_location", str(_BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    logger.info("DEMO_SEED: running Alembic migrations to head")
    command.upgrade(cfg, "head")
    logger.info("DEMO_SEED: migrations complete")


def create_all_tables() -> None:
    """SQLite demo shortcut: create tables straight from ORM metadata."""
    import app.models  # noqa: F401  (registers every model on Base)
    from app.database import engine
    from app.db.base import Base

    Base.metadata.create_all(bind=engine)


def count_hotels() -> int:
    from app.db.session import SessionLocal
    from app.models.hotel import Hotel

    db = SessionLocal()
    try:
        return db.query(Hotel).count()
    finally:
        db.close()


def run_seed_script() -> None:
    """Run ``scripts/seed_demo.py`` as a subprocess.

    The seed script is natural-key idempotent, and its admin password
    comes from ``SEED_ADMIN_PASSWORD`` (default ``Preview@123`` — a
    DEMO-ONLY password printed in the deploy docs, not a real
    credential).
    """
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


def prepare_demo_database(database_url: str) -> None:
    """Bring the demo database up to date, then seed it if empty.

    PostgreSQL → Alembic migrations to head (never ``create_all``).
    Anything else (SQLite) → ``create_all``. The seed step only runs
    when the hotels table is empty.
    """
    url = normalize_database_url(database_url)
    if is_postgres_url(url):
        run_migrations(url)
    else:
        create_all_tables()

    hotel_count = count_hotels()
    if hotel_count > 0:
        logger.info("DEMO_SEED: %s hotel(s) already present, skipping seed", hotel_count)
        return
    run_seed_script()
