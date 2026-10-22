import uuid

from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _new_public_id() -> str:
    """Non-sequential public identifier for a hotel (widget/integration use).

    The internal integer ``id`` is never exposed to guests or partners; the
    public id is a random uuid4 hex token, safe to embed in a website.
    """
    return uuid.uuid4().hex


class Hotel(Base):
    __tablename__ = "hotels"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Public, non-sequential identifier (unique, indexed). Resolved by the
    # public widget API and the server-to-server integration API; the
    # internal integer id is never accepted there.
    public_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
        index=True,
        default=_new_public_id,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Guest-facing check-in / check-out times (e.g. "14:00" / "11:00").
    check_in_time: Mapped[str | None] = mapped_column(String(5), nullable=True)
    check_out_time: Mapped[str | None] = mapped_column(String(5), nullable=True)
    timezone: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="Asia/Kolkata",
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="INR",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    # --- Server-to-server integration credentials (Master Prompt §12) -----
    # Dedicated credential fields: the inbound secret is required in raw
    # form by the server to verify HMAC-SHA256 request signatures, so it
    # cannot be stored as a one-way hash. It is treated like the other
    # provider secrets in this codebase (env-held bot tokens): never
    # returned by any API after the one-time generation response, never
    # logged, and never included in staff-facing list/detail payloads.
    # ``integration_secret_fingerprint`` (SHA-256 hex prefix of the secret)
    # is the only derived value safe to display for identification.
    integration_secret: Mapped[str | None] = mapped_column(String(255), nullable=True)
    integration_secret_fingerprint: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # Optional outbound webhook (async integration responses): the hotel's
    # endpoint plus the signing secret used to sign deliveries. The signing
    # secret must be retrievable by the server to compute HMAC signatures,
    # so it lives in this dedicated field under the same rules as above.
    integration_webhook_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    integration_webhook_secret: Mapped[str | None] = mapped_column(String(255), nullable=True)
