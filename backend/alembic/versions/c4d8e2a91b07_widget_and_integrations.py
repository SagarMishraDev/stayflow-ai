"""widget public_id, check-in/out times, and integration tables

Revision ID: c4d8e2a91b07
Revises: 6fac09f32444
Create Date: 2026-10-20

Master Prompt §5/§11/§12:

- ``hotels.public_id`` — non-sequential public identifier (uuid4 hex),
  unique + indexed. Existing rows are backfilled with fresh random ids;
  the column ends NOT NULL. The widget and integration APIs resolve
  hotels by this id only, never by the internal integer id.
- ``hotels.check_in_time`` / ``hotels.check_out_time`` — nullable
  guest-facing times ("HH:MM").
- ``hotels.integration_secret`` / ``integration_secret_fingerprint`` /
  ``integration_webhook_url`` / ``integration_webhook_secret`` — per-hotel
  server-to-server integration credentials (§12), all nullable.
- New tables: ``integration_idempotency_keys`` (hotel-scoped unique
  idempotency store), ``integration_request_logs`` (minimal request log),
  ``integration_nonces`` (replay protection).

Hand-written (this repo's autogenerate history makes hand-review the
norm) and batch-mode for the hotels changes so it applies cleanly on
both PostgreSQL and SQLite.
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4d8e2a91b07"
down_revision: str | Sequence[str] | None = "6fac09f32444"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("hotels") as batch_op:
        batch_op.add_column(sa.Column("public_id", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("check_in_time", sa.String(length=5), nullable=True))
        batch_op.add_column(sa.Column("check_out_time", sa.String(length=5), nullable=True))
        batch_op.add_column(sa.Column("integration_secret", sa.String(length=255), nullable=True))
        batch_op.add_column(
            sa.Column("integration_secret_fingerprint", sa.String(length=16), nullable=True)
        )
        batch_op.add_column(
            sa.Column("integration_webhook_url", sa.String(length=500), nullable=True)
        )
        batch_op.add_column(
            sa.Column("integration_webhook_secret", sa.String(length=255), nullable=True)
        )

    # Backfill public_id for existing hotels with fresh random tokens.
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id FROM hotels WHERE public_id IS NULL")).fetchall()
    for (hotel_id,) in rows:
        bind.execute(
            sa.text("UPDATE hotels SET public_id = :pid WHERE id = :hid"),
            {"pid": uuid.uuid4().hex, "hid": hotel_id},
        )

    with op.batch_alter_table("hotels") as batch_op:
        batch_op.alter_column("public_id", existing_type=sa.String(length=64), nullable=False)
    op.create_index("ix_hotels_public_id", "hotels", ["public_id"], unique=True)

    op.create_table(
        "integration_idempotency_keys",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("hotel_id", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=True),
        sa.Column("response_status", sa.Integer(), nullable=False),
        sa.Column("response_body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["hotel_id"], ["hotels.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "hotel_id", "idempotency_key", name="uq_integration_idempotency_hotel_key"
        ),
    )
    op.create_index(
        "ix_integration_idempotency_keys_hotel_id",
        "integration_idempotency_keys",
        ["hotel_id"],
    )

    op.create_table(
        "integration_request_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("hotel_id", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("conversation_id", sa.Integer(), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.Column("webhook_delivered", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["hotel_id"], ["hotels.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_integration_request_logs_hotel_id", "integration_request_logs", ["hotel_id"]
    )

    op.create_table(
        "integration_nonces",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("hotel_id", sa.Integer(), nullable=False),
        sa.Column("signature", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["hotel_id"], ["hotels.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_integration_nonces_hotel_id", "integration_nonces", ["hotel_id"])
    op.create_index(
        "ix_integration_nonces_signature", "integration_nonces", ["signature"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_integration_nonces_signature", table_name="integration_nonces")
    op.drop_index("ix_integration_nonces_hotel_id", table_name="integration_nonces")
    op.drop_table("integration_nonces")

    op.drop_index("ix_integration_request_logs_hotel_id", table_name="integration_request_logs")
    op.drop_table("integration_request_logs")

    op.drop_index(
        "ix_integration_idempotency_keys_hotel_id",
        table_name="integration_idempotency_keys",
    )
    op.drop_table("integration_idempotency_keys")

    op.drop_index("ix_hotels_public_id", table_name="hotels")
    with op.batch_alter_table("hotels") as batch_op:
        batch_op.drop_column("integration_webhook_secret")
        batch_op.drop_column("integration_webhook_url")
        batch_op.drop_column("integration_secret_fingerprint")
        batch_op.drop_column("integration_secret")
        batch_op.drop_column("check_out_time")
        batch_op.drop_column("check_in_time")
        batch_op.drop_column("public_id")
