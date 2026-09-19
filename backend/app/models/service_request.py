from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ServiceRequest(Base):
    __tablename__ = "service_requests"

    id: Mapped[int] = mapped_column(primary_key=True)

    hotel_id: Mapped[int] = mapped_column(
        ForeignKey("hotels.id"),
        nullable=False,
    )

    guest_id: Mapped[int] = mapped_column(
        ForeignKey("guests.id"),
        nullable=False,
    )

    service_id: Mapped[int] = mapped_column(
        ForeignKey("services.id"),
        nullable=False,
    )

    room_number: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )

    request_text: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="PENDING",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )