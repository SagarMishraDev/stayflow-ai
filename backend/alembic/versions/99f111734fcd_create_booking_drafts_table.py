"""create booking drafts table

Revision ID: 99f111734fcd
Revises: fa951b5035d8
Create Date: 2026-09-29 12:45:00.000000

Booking drafts back the agent's two-phase booking flow: preview_booking
validates and prices a prospective booking and persists a draft with an
expiry; create_booking consumes a valid, unexpired draft and re-validates
availability/pricing at confirm time.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "99f111734fcd"
down_revision: str | Sequence[str] | None = "fa951b5035d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "booking_drafts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("hotel_id", sa.Integer(), nullable=False),
        sa.Column("guest_id", sa.Integer(), nullable=False),
        sa.Column("room_id", sa.Integer(), nullable=False),
        sa.Column("check_in", sa.Date(), nullable=False),
        sa.Column("check_out", sa.Date(), nullable=False),
        sa.Column("number_of_guests", sa.Integer(), nullable=False),
        sa.Column("total_price", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["guest_id"],
            ["guests.id"],
        ),
        sa.ForeignKeyConstraint(
            ["hotel_id"],
            ["hotels.id"],
        ),
        sa.ForeignKeyConstraint(
            ["room_id"],
            ["rooms.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_booking_drafts_hotel_status",
        "booking_drafts",
        ["hotel_id", "status"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_booking_drafts_hotel_status", table_name="booking_drafts")
    op.drop_table("booking_drafts")
