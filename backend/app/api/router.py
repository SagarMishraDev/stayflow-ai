from fastapi import APIRouter, Depends
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.models.hotel import Hotel
from app.schemas.health import HealthResponse
from app.schemas.hotel import HotelResponse

router = APIRouter()

settings = get_settings()


@router.get("/health", response_model=HealthResponse, tags=["system"])
async def health_check() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version=settings.app_version,
    )


@router.get("/db-check", tags=["system"])
def database_check(db: Session = Depends(get_db, scope="function")) -> dict[str, str]:
    db.execute(text("SELECT 1"))

    return {
        "status": "ok",
        "database": "connected",
    }


@router.get(
    "/hotels",
    response_model=list[HotelResponse],
    tags=["hotels"],
)
def get_hotels(
    db: Session = Depends(get_db, scope="function"),
) -> list[HotelResponse]:
    hotels = db.scalars(
        select(Hotel)
    ).all()

    return hotels