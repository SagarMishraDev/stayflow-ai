from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class HotelUser(Base):
    __tablename__ = "hotel_users"

    id: Mapped[int] = mapped_column(primary_key=True)

    hotel_id: Mapped[int] = mapped_column(
        ForeignKey("hotels.id"),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    email: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    phone: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )

    role: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    # Department the staff member belongs to (front_office, kitchen,
    # housekeeping, finance, maintenance, ...). Free-form label set by
    # the creating admin/manager; permissions come from `role`, not this.
    department: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    # Session generation. Bumped on password change, role change and
    # deactivation; JWTs carry the version they were minted with and
    # `get_current_user` rejects stale ones, so privileged changes revoke
    # existing sessions immediately.
    token_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
