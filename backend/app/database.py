from sqlalchemy import create_engine

from app.core.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.database_url,
)


def test_connection() -> None:
    with engine.connect() as _connection:
        print("Database connection successful!")
