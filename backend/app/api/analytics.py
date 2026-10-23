"""Analytics + payments API (HMS upgrade Phase 4).

All endpoints are staff-JWT protected, hotel-scoped (cross-hotel = 403,
super admin exempt), and compute from real rows via
``app.services.analytics`` — no dummy data anywhere. Money is returned
as decimal strings. Accounting rules: HMS_UPGRADE_REPORT.md Phase 1.
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.roles import HOTEL_ADMIN, SUPER_ADMIN, is_super_admin, normalize_role
from app.core.security import require_roles
from app.db.session import get_db
from app.models.booking import Booking
from app.models.hotel import Hotel
from app.models.hotel_user import HotelUser
from app.models.payment import PAYMENT_METHODS, PAYMENT_STATUSES, Payment
from app.services import analytics as analytics_service
from app.services.audit import log_action

router = APIRouter(tags=["analytics"])

_ANALYTICS_VIEW = require_roles(HOTEL_ADMIN, SUPER_ADMIN, "manager", "accountant")
_FINANCE_VIEW = require_roles(HOTEL_ADMIN, SUPER_ADMIN, "manager", "accountant")
_PAYMENT_RECORD = require_roles(
    HOTEL_ADMIN, SUPER_ADMIN, "manager", "accountant", "receptionist", "staff"
)


def _scope_hotel(db: Session, hotel_id: int, current_user: HotelUser) -> Hotel:
    hotel = db.get(Hotel, hotel_id)
    if hotel is None:
        raise HTTPException(status_code=404, detail="Hotel not found")
    if not is_super_admin(current_user.role) and hotel.id != current_user.hotel_id:
        raise HTTPException(status_code=403, detail="Hotel access denied")
    return hotel


def _range(range_key: str, start: date | None, end: date | None) -> tuple[date | None, date | None]:
    try:
        return analytics_service.resolve_range(
            range_key, today=date.today(), custom_start=start, custom_end=end
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/analytics/overview")
def analytics_overview(
    hotel_id: int,
    range: str = Query("month"),  # noqa: A002 - API name per spec
    start: date | None = None,
    end: date | None = None,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(_ANALYTICS_VIEW),
) -> dict:
    _scope_hotel(db, hotel_id, current_user)
    start_d, end_d = _range(range, start, end)
    return analytics_service.kpi_overview(db, hotel_id, start_d, end_d, today=date.today())


@router.get("/analytics/series")
def analytics_series(
    hotel_id: int,
    range: str = Query("month"),  # noqa: A002
    group_by: str = Query("day"),
    start: date | None = None,
    end: date | None = None,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(_ANALYTICS_VIEW),
) -> dict:
    _scope_hotel(db, hotel_id, current_user)
    if group_by not in ("hour", "day", "week", "month", "year"):
        raise HTTPException(status_code=422, detail="invalid group_by")
    start_d, end_d = _range(range, start, end)
    return {
        "series": analytics_service.revenue_series(
            db, hotel_id, start_d, end_d, group_by=group_by, today=date.today()
        )
    }


@router.get("/analytics/compare")
def analytics_compare(
    hotel_id: int,
    range_a: str = Query("month"),
    range_b: str = Query("last_month"),
    a_start: date | None = None,
    a_end: date | None = None,
    b_start: date | None = None,
    b_end: date | None = None,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(_ANALYTICS_VIEW),
) -> dict:
    _scope_hotel(db, hotel_id, current_user)
    a = _range(range_a, a_start, a_end)
    b = _range(range_b, b_start, b_end)
    return analytics_service.compare_periods(db, hotel_id, a, b, today=date.today())


@router.get("/analytics/breakdowns")
def analytics_breakdowns(
    hotel_id: int,
    range: str = Query("month"),  # noqa: A002
    start: date | None = None,
    end: date | None = None,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(_FINANCE_VIEW),
) -> dict:
    _scope_hotel(db, hotel_id, current_user)
    start_d, end_d = _range(range, start, end)
    return analytics_service.breakdowns(db, hotel_id, start_d, end_d, today=date.today())


@router.get("/analytics/room-popularity")
def analytics_room_popularity(
    hotel_id: int,
    range: str = Query("month"),  # noqa: A002
    start: date | None = None,
    end: date | None = None,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(_ANALYTICS_VIEW),
) -> dict:
    _scope_hotel(db, hotel_id, current_user)
    start_d, end_d = _range(range, start, end)
    return analytics_service.room_popularity(db, hotel_id, start_d, end_d, today=date.today())


@router.get("/analytics/export")
def analytics_export(
    hotel_id: int,
    dataset: str = Query("series"),
    range: str = Query("month"),  # noqa: A002
    group_by: str = Query("day"),
    start: date | None = None,
    end: date | None = None,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(_ANALYTICS_VIEW),
) -> PlainTextResponse:
    _scope_hotel(db, hotel_id, current_user)
    start_d, end_d = _range(range, start, end)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    if dataset == "series":
        writer.writerow(["period", "revenue", "bookings"])
        for row in analytics_service.revenue_series(
            db, hotel_id, start_d, end_d, group_by=group_by, today=date.today()
        ):
            writer.writerow([row["period"], row["revenue"], row["bookings"]])
    elif dataset == "room-popularity":
        writer.writerow(
            ["room_type", "bookings", "revenue", "occupied_room_nights", "occupancy_rate"]
        )
        result = analytics_service.room_popularity(db, hotel_id, start_d, end_d, today=date.today())
        for row in result["rooms"]:
            writer.writerow(
                [
                    row["room_type"],
                    row["bookings"],
                    row["revenue"],
                    row["occupied_room_nights"],
                    row["occupancy_rate"],
                ]
            )
    else:
        raise HTTPException(status_code=422, detail="unknown dataset")
    return PlainTextResponse(
        buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{dataset}.csv"'},
    )


# --------------------------------------------------------------------- #
# Payments                                                               #
# --------------------------------------------------------------------- #
class PaymentCreate(BaseModel):
    hotel_id: int
    booking_id: int
    amount: Decimal = Field(gt=0)
    method: str = "cash"
    status: str = "captured"
    reference: str | None = None

    @field_validator("method")
    @classmethod
    def _method(cls, v: str) -> str:
        if v not in PAYMENT_METHODS:
            raise ValueError(f"method must be one of {PAYMENT_METHODS}")
        return v

    @field_validator("status")
    @classmethod
    def _status(cls, v: str) -> str:
        if v not in PAYMENT_STATUSES:
            raise ValueError(f"status must be one of {PAYMENT_STATUSES}")
        return v


class PaymentResponse(BaseModel):
    id: int
    hotel_id: int
    booking_id: int
    amount: Decimal
    method: str
    status: str
    reference: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


@router.post("/payments", response_model=PaymentResponse, status_code=201)
def record_payment(
    payload: PaymentCreate,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(_PAYMENT_RECORD),
) -> Payment:
    _scope_hotel(db, payload.hotel_id, current_user)
    booking = db.get(Booking, payload.booking_id)
    if booking is None or booking.hotel_id != payload.hotel_id:
        raise HTTPException(status_code=404, detail="Booking not found")
    payment = Payment(
        hotel_id=payload.hotel_id,
        booking_id=payload.booking_id,
        amount=payload.amount,
        method=payload.method,
        status=payload.status,
        reference=payload.reference,
    )
    db.add(payment)
    db.flush()
    log_action(
        db,
        hotel_id=payload.hotel_id,
        actor_type="staff",
        actor_id=current_user.id,
        action="payment.recorded",
        entity_type="payment",
        entity_id=payment.id,
        details={"booking_id": payload.booking_id, "status": payload.status},
    )
    db.commit()
    db.refresh(payment)
    return payment


@router.get("/payments", response_model=list[PaymentResponse])
def list_payments(
    hotel_id: int,
    booking_id: int | None = None,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(_FINANCE_VIEW),
) -> list[Payment]:
    _scope_hotel(db, hotel_id, current_user)
    stmt = select(Payment).where(Payment.hotel_id == hotel_id)
    if booking_id is not None:
        stmt = stmt.where(Payment.booking_id == booking_id)
    return list(db.scalars(stmt.order_by(Payment.id.desc()).limit(500)).all())


# Keep normalize_role import used by role tooling/tests (fail-closed check).
_ = normalize_role
