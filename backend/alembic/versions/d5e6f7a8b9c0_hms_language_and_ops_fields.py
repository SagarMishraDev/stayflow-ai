"""HMS upgrade: conversation language preference + ops/analytics fields.

Adds, in one revision (applied together by the HMS upgrade):
- conversations.preferred_language (Phase 2)
- hotel_users.department, hotel_users.token_version (Phase 3)
- bookings.source (Phase 4)
- payments table (Phase 4)
- hotel_rooms.cleaning_status (Phase 5)
- orders.status_reason, orders.scheduled_for (Phase 5)
- notifications.target_role (Phase 5)

Revision ID: d5e6f7a8b9c0
Revises: c4d8e2a91b07
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d5e6f7a8b9c0"
down_revision: str | None = "c4d8e2a91b07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("preferred_language", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "hotel_users",
        sa.Column("department", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "hotel_users",
        sa.Column(
            "token_version",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "bookings",
        sa.Column("source", sa.String(length=50), nullable=True),
    )
    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("hotel_id", sa.Integer(), nullable=False),
        sa.Column("booking_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("method", sa.String(length=50), nullable=False, server_default="cash"),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="pending"),
        sa.Column("reference", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"]),
        sa.ForeignKeyConstraint(["hotel_id"], ["hotels.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_payments_hotel_created", "payments", ["hotel_id", "created_at"])
    op.create_index("ix_payments_booking", "payments", ["booking_id"])
    op.add_column(
        "hotel_rooms",
        sa.Column(
            "cleaning_status",
            sa.String(length=50),
            nullable=False,
            server_default="READY",
        ),
    )
    op.add_column(
        "orders",
        sa.Column("status_reason", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "notifications",
        sa.Column("target_role", sa.String(length=50), nullable=True),
    )
    # Notifications become addressable to a role queue as well as a user.
    with op.batch_alter_table("notifications") as batch_op:
        batch_op.alter_column("user_id", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    with op.batch_alter_table("notifications") as batch_op:
        batch_op.alter_column("user_id", existing_type=sa.Integer(), nullable=False)
    op.drop_column("notifications", "target_role")
    op.drop_column("orders", "scheduled_for")
    op.drop_column("orders", "status_reason")
    op.drop_column("hotel_rooms", "cleaning_status")
    op.drop_index("ix_payments_booking", table_name="payments")
    op.drop_index("ix_payments_hotel_created", table_name="payments")
    op.drop_table("payments")
    op.drop_column("bookings", "source")
    op.drop_column("hotel_users", "token_version")
    op.drop_column("hotel_users", "department")
    op.drop_column("conversations", "preferred_language")
