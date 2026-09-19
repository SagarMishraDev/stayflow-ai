from app.db.session import SessionLocal


def test_database_session() -> None:
    db = SessionLocal()

    try:
        connection = db.connection()
        assert connection is not None
    finally:
        db.close()
