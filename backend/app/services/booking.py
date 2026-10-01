from datetime import date
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.availability import Availability
from app.models.booking import Booking
from app.models.guest import Guest
from app.models.rate import Rate
from app.models.room import Room


def create_booking(
    db: Session,
    hotel_id: int,
    guest_id: int,
    room_id: int,
    check_in: date,
    check_out: date,
    number_of_guests: int,
    booking_status: str = "PENDING",
) -> Booking:
    guest = db.get(Guest, guest_id)
    if guest is None:
        raise HTTPException(
            status_code=404,
            detail="Guest not found",
        )

    room = db.get(Room, room_id)
    if room is None:
        raise HTTPException(
            status_code=404,
            detail="Room not found",
        )

    if check_out <= check_in:
        raise HTTPException(
            status_code=422,
            detail="check_out must be after check_in",
        )

    if guest.hotel_id != hotel_id:
        raise HTTPException(
            status_code=422,
            detail="Guest does not belong to this hotel",
        )

    if room.hotel_id != hotel_id:
        raise HTTPException(
            status_code=422,
            detail="Room does not belong to this hotel",
        )

    if number_of_guests > room.capacity:
        raise HTTPException(
            status_code=422,
            detail="Number of guests exceeds room capacity",
        )

    nights = (check_out - check_in).days

    availability_rows = db.scalars(
        select(Availability)
        .where(
            Availability.room_id == room_id,
            Availability.date >= check_in,
            Availability.date < check_out,
            Availability.is_active.is_(True),
        )
        .order_by(Availability.date)
        .with_for_update()
    ).all()

    if len(availability_rows) != nights:
        raise HTTPException(
            status_code=422,
            detail="Availability is not configured for all requested dates",
        )

    for row in availability_rows:
        if row.available_rooms <= 0:
            raise HTTPException(
                status_code=409,
                detail=f"No rooms are available for {row.date.isoformat()}",
            )

    rates = db.scalars(
        select(Rate).where(
            Rate.room_id == room_id,
            Rate.date >= check_in,
            Rate.date < check_out,
            Rate.is_active.is_(True),
        )
    ).all()

    if len(rates) != nights:
        raise HTTPException(
            status_code=422,
            detail="Rate is not configured for all requested dates",
        )

    final_price = sum(
        (rate.price for rate in rates),
        Decimal("0.00"),
    )

    for row in availability_rows:
        row.available_rooms -= 1

    new_booking = Booking(
        hotel_id=hotel_id,
        guest_id=guest_id,
        room_id=room_id,
        check_in=check_in,
        check_out=check_out,
        number_of_guests=number_of_guests,
        final_price=final_price,
        booking_status=booking_status,
    )

    db.add(new_booking)
    db.commit()
    db.refresh(new_booking)

    return new_booking
