"""add guest channel identifiers

Adds messaging-channel identity columns to ``guests`` for the Telegram and
WhatsApp bot connectors (Prompt-1 sections 4-5):

- ``telegram_chat_id`` (nullable) with a composite unique constraint on
  ``(hotel_id, telegram_chat_id)``
- ``whatsapp_number`` (nullable) with a composite unique constraint on
  ``(hotel_id, whatsapp_number)``

Repeat webhooks from the same sender resolve to one guest row instead of
creating duplicates. NULLs are not considered equal by PostgreSQL unique
constraints, so existing guests without channel identities are unaffected.

Revision ID: 1505f2ad0a74
Revises: a1b2c3d4e5f6
Create Date: 2026-09-29

NOTE: the autogenerate for this revision was reviewed and discarded — this
repo's ``alembic/env.py`` only imports ``app.db.base.Base`` without importing
``app.models``, so ``target_metadata`` is empty and autogenerate emits
spurious ``drop_table`` calls for every table. The operations below are
hand-written and verified against the model.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1505f2ad0a74"
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "guests",
        sa.Column("telegram_chat_id", sa.String(64), nullable=True),
    )
    op.add_column(
        "guests",
        sa.Column("whatsapp_number", sa.String(30), nullable=True),
    )
    op.create_unique_constraint(
        "uq_guests_hotel_telegram_chat_id",
        "guests",
        ["hotel_id", "telegram_chat_id"],
    )
    op.create_unique_constraint(
        "uq_guests_hotel_whatsapp_number",
        "guests",
        ["hotel_id", "whatsapp_number"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_guests_hotel_whatsapp_number", "guests", type_="unique")
    op.drop_constraint("uq_guests_hotel_telegram_chat_id", "guests", type_="unique")
    op.drop_column("guests", "whatsapp_number")
    op.drop_column("guests", "telegram_chat_id")
