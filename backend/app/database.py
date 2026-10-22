from sqlalchemy import create_engine

from app.core.config import get_settings

settings = get_settings()

# Neon (serverless PostgreSQL) suspends its compute after a few idle
# minutes and kills/recycles open connections, while this process stays
# awake (health checks never touch the DB). A bare engine's pool fills
# with dead psycopg sockets: the next DB request checks one out, sends a
# query, and waits forever — no timeouts anywhere. PostgreSQL engines
# therefore get:
#   pool_pre_ping  — dead pooled connections are detected and replaced
#   pool_recycle   — connections recycled after 180s, inside Neon's
#                    idle window, so the pool never holds stale sockets
#   keepalives     — TCP keepalives keep live connections provably live
#   connect_timeout — a fresh connection fails in 10s, never hangs
#   statement_timeout — a stuck query fails server-side in 60s
# SQLite/test engines keep the previous bare behaviour, byte-identical.
_POSTGRES_CONNECT_ARGS = {
    "connect_timeout": 10,
    "keepalives": 1,
    "keepalives_idle": 60,
    "keepalives_interval": 10,
    "keepalives_count": 5,
    "options": "-c statement_timeout=60000",
}


def _engine_options(database_url: str) -> dict:
    """create_engine kwargs for ``database_url`` (PostgreSQL hardening only)."""
    if database_url.startswith("postgres"):
        return {
            "pool_pre_ping": True,
            "pool_recycle": 180,
            "connect_args": dict(_POSTGRES_CONNECT_ARGS),
        }
    return {}


engine = create_engine(
    settings.database_url,
    **_engine_options(settings.database_url),
)


def test_connection() -> None:
    with engine.connect() as _connection:
        print("Database connection successful!")
