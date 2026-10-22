"""Demo bootstrap: DATABASE_URL normalization + Postgres/SQLite branch.

Covers the switch of the public demo from mock+SQLite to the real
Mercury provider on a Neon PostgreSQL database:

- ``normalize_database_url`` (app/core/config.py) rewrites the bare
  ``postgres://`` / ``postgresql://`` URLs that Neon hands out to the
  ``postgresql+psycopg://`` driver this project ships, and leaves every
  other URL untouched. It is applied once, in ``Settings``, so the app
  engine, the Alembic env and the demo bootstrap all agree.
- ``prepare_demo_database`` (app/demo_bootstrap.py) runs Alembic
  migrations for PostgreSQL and ``create_all`` for SQLite, then seeds
  only when the hotels table is empty.

There is no real PostgreSQL in the test environment, so the branch
tests fake the migration / create_all / hotel-count / seed steps and
assert which ones run for each URL shape.

App imports are deliberately lazy (inside the tests) so this module's
collection stays side-effect free.
"""

import pytest

_NEON_RAW = (
    "postgresql://neondb_owner:s3cret@ep-cool-123.us-east-1.aws.neon.tech/neondb?sslmode=require"
)
_NEON_NORMALIZED = (
    "postgresql+psycopg://neondb_owner:s3cret@ep-cool-123.us-east-1.aws.neon.tech"
    "/neondb?sslmode=require"
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Neon-style handouts: legacy scheme and bare scheme.
        ("postgres://user:pass@host/db", "postgresql+psycopg://user:pass@host/db"),
        (_NEON_RAW, _NEON_NORMALIZED),
        (
            "postgresql://user:pass@ep-x-pooler.us-east-1.aws.neon.tech/db?sslmode=require",
            "postgresql+psycopg://user:pass@ep-x-pooler.us-east-1.aws.neon.tech/db?sslmode=require",
        ),
        # Already qualified → untouched.
        (
            "postgresql+psycopg://user:pass@localhost:5432/stayflow_test",
            "postgresql+psycopg://user:pass@localhost:5432/stayflow_test",
        ),
        (
            "postgresql+asyncpg://user:pass@localhost/db",
            "postgresql+asyncpg://user:pass@localhost/db",
        ),
        # SQLite (local demo + test suite) → untouched.
        ("sqlite:///./stayflow.db", "sqlite:///./stayflow.db"),
        ("sqlite:////tmp/stayflow-demo.db", "sqlite:////tmp/stayflow-demo.db"),
    ],
)
def test_normalize_database_url(raw, expected):
    from app.core.config import normalize_database_url

    assert normalize_database_url(raw) == expected


def test_normalize_database_url_is_idempotent():
    from app.core.config import normalize_database_url

    once = normalize_database_url(_NEON_RAW)
    assert normalize_database_url(once) == once


def test_settings_normalizes_database_url(monkeypatch):
    from app.core.config import Settings

    # The validator on Settings is the single application point.
    monkeypatch.setenv("DATABASE_URL", _NEON_RAW)
    settings = Settings(_env_file=None)
    assert settings.database_url == _NEON_NORMALIZED


def test_settings_leaves_sqlite_url_untouched(monkeypatch):
    from app.core.config import Settings

    monkeypatch.setenv("DATABASE_URL", "sqlite:////tmp/demo.db")
    settings = Settings(_env_file=None)
    assert settings.database_url == "sqlite:////tmp/demo.db"


class _FakeSteps:
    """Fakes for demo_bootstrap's side-effecting steps; records calls."""

    def __init__(self, monkeypatch, *, hotels=0, migrate_error=None):
        from app import demo_bootstrap

        self.calls: list[tuple] = []

        def fake_migrate(url):
            self.calls.append(("migrate", url))
            if migrate_error is not None:
                raise migrate_error

        monkeypatch.setattr(demo_bootstrap, "run_migrations", fake_migrate)
        monkeypatch.setattr(
            demo_bootstrap, "create_all_tables", lambda: self.calls.append(("create_all",))
        )
        monkeypatch.setattr(demo_bootstrap, "count_hotels", lambda: hotels)
        monkeypatch.setattr(demo_bootstrap, "run_seed_script", lambda: self.calls.append(("seed",)))


def test_postgres_runs_migrations_not_create_all_and_seeds_when_empty(monkeypatch):
    from app import demo_bootstrap

    steps = _FakeSteps(monkeypatch, hotels=0)
    # Raw Neon URL in → prepare normalizes before branching.
    demo_bootstrap.prepare_demo_database(_NEON_RAW)
    assert steps.calls == [("migrate", _NEON_NORMALIZED), ("seed",)]


def test_postgres_skips_seed_when_hotels_exist(monkeypatch):
    from app import demo_bootstrap

    steps = _FakeSteps(monkeypatch, hotels=3)
    demo_bootstrap.prepare_demo_database(_NEON_NORMALIZED)
    assert steps.calls == [("migrate", _NEON_NORMALIZED)]


def test_sqlite_uses_create_all_not_migrations_and_seeds_when_empty(monkeypatch):
    from app import demo_bootstrap

    steps = _FakeSteps(monkeypatch, hotels=0)
    demo_bootstrap.prepare_demo_database("sqlite:////tmp/demo.db")
    assert steps.calls == [("create_all",), ("seed",)]


def test_sqlite_skips_seed_when_hotels_exist(monkeypatch):
    from app import demo_bootstrap

    steps = _FakeSteps(monkeypatch, hotels=5)
    demo_bootstrap.prepare_demo_database("sqlite:////tmp/demo.db")
    assert steps.calls == [("create_all",)]


def test_migration_failure_propagates_and_seed_never_runs(monkeypatch):
    from app import demo_bootstrap

    steps = _FakeSteps(monkeypatch, hotels=0, migrate_error=RuntimeError("boom"))
    with pytest.raises(RuntimeError, match="boom"):
        demo_bootstrap.prepare_demo_database(_NEON_RAW)
    assert steps.calls == [("migrate", _NEON_NORMALIZED)]
