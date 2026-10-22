from sqlalchemy import create_engine, text

from app.database import _POSTGRES_CONNECT_ARGS, _engine_options, engine
from app.db.session import SessionLocal

_POSTGRES_URL = "postgresql+psycopg://user:pass@ep-example.aws.neon.tech/neondb?sslmode=require"


def test_database_session() -> None:
    db = SessionLocal()

    try:
        connection = db.connection()
        assert connection is not None
    finally:
        db.close()


def test_engine_options_empty_for_sqlite() -> None:
    # SQLite/test engines keep the previous bare behaviour: no
    # PostgreSQL connect_args, no pool overrides forced.
    assert _engine_options("sqlite:///./stayflow_e2e.db") == {}
    assert _engine_options("sqlite:///:memory:") == {}


def test_engine_options_harden_postgres() -> None:
    options = _engine_options(_POSTGRES_URL)

    assert options["pool_pre_ping"] is True
    assert options["pool_recycle"] == 180
    assert options["connect_args"] == _POSTGRES_CONNECT_ARGS


def test_postgres_connect_args_carry_timeouts_and_keepalives() -> None:
    connect_args = _engine_options(_POSTGRES_URL)["connect_args"]

    assert connect_args["connect_timeout"] == 10
    assert connect_args["keepalives"] == 1
    assert connect_args["keepalives_idle"] == 60
    assert connect_args["keepalives_interval"] == 10
    assert connect_args["keepalives_count"] == 5
    # A stuck query must fail server-side, never hang forever.
    assert connect_args["options"] == "-c statement_timeout=60000"


def test_postgres_engine_pool_is_hardened() -> None:
    # No live connection: create_engine is lazy, so the pool can be
    # introspected without reaching the (nonexistent) host.
    pg_engine = create_engine(_POSTGRES_URL, **_engine_options(_POSTGRES_URL))
    try:
        assert pg_engine.pool._pre_ping is True
        assert pg_engine.pool._recycle == 180
    finally:
        pg_engine.dispose()


def test_sqlite_engine_still_executes() -> None:
    # The app's own engine (DATABASE_URL = the e2e SQLite recipe in the
    # suite) must keep working untouched by the PostgreSQL options.
    assert engine.dialect.name == "sqlite"
    with engine.connect() as connection:
        assert connection.execute(text("SELECT 1")).scalar() == 1
