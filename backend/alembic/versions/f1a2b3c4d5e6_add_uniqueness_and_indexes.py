"""add uniqueness constraints and performance indexes

Revision ID: f1a2b3c4d5e6
Revises: e9af9a04db09
Create Date: 2026-09-29 00:00:00.000000

- Unique (room_id, date) on rates and availability to prevent duplicate rows
  for the same room/date. Pre-existing duplicates are removed first
  (keeping the earliest row per room/date).
- Indexes on hot query paths: bookings (room/date/status/guest),
  messages, conversations, audit logs, service requests, orders.
  (No separate plain indexes on rates/availability (room_id, date): the
  unique constraints already create backing indexes for those.)
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f1a2b3c4d5e6"
down_revision: str | Sequence[str] | None = "e9af9a04db09"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEDUP_SQL = """
DELETE FROM {table} a USING {table} b
WHERE a.id > b.id
  AND a.room_id = b.room_id
  AND a.date = b.date
"""


def upgrade() -> None:
    """Upgrade schema."""
    # Remove pre-existing duplicates so the unique constraints can be created.
    for table in ("rates", "availability"):
        op.execute(sa.text(_DEDUP_SQL.format(table=table)))

    op.create_unique_constraint("uq_rates_room_date", "rates", ["room_id", "date"])
    op.create_unique_constraint("uq_availability_room_date", "availability", ["room_id", "date"])

    op.create_index("ix_bookings_room_dates", "bookings", ["room_id", "check_in", "check_out"])
    op.create_index("ix_bookings_status", "bookings", ["booking_status"])
    op.create_index("ix_bookings_guest", "bookings", ["guest_id"])
    op.create_index("ix_messages_conversation", "messages", ["conversation_id"])
    op.create_index("ix_conversations_guest", "conversations", ["guest_id"])
    op.create_index("ix_audit_logs_hotel", "audit_logs", ["hotel_id"])
    op.create_index("ix_service_requests_hotel", "service_requests", ["hotel_id"])
    op.create_index("ix_orders_guest", "orders", ["guest_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_orders_guest", table_name="orders")
    op.drop_index("ix_service_requests_hotel", table_name="service_requests")
    op.drop_index("ix_audit_logs_hotel", table_name="audit_logs")
    op.drop_index("ix_conversations_guest", table_name="conversations")
    op.drop_index("ix_messages_conversation", table_name="messages")
    op.drop_index("ix_bookings_guest", table_name="bookings")
    op.drop_index("ix_bookings_status", table_name="bookings")
    op.drop_index("ix_bookings_room_dates", table_name="bookings")

    op.drop_constraint("uq_availability_room_date", "availability", type_="unique")
    op.drop_constraint("uq_rates_room_date", "rates", type_="unique")
