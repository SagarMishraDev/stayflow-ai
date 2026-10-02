"""add ingestion status to hotel knowledge documents

Revision ID: 6fac09f32444
Revises: 3d4e5f6a7b8c
Create Date: 2026-09-29 18:30:00.000000

Adds the ingestion-lifecycle columns backing the background job queue
(Prompt-1 §6) to ``hotel_documents``:

- ``status`` — "processing" | "ready" | "failed" (default "processing").
  Existing rows (ingested synchronously before the queue existed) are
  backfilled to "ready": they already have their chunks persisted.
- ``error`` — short failure note, set when ``status`` becomes "failed".

Reviewed by hand: only these two columns, nothing else.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6fac09f32444"
down_revision: str | Sequence[str] | None = "3d4e5f6a7b8c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Added nullable first so existing rows can be backfilled; the column
    # ends NOT NULL with no server default, matching the model exactly
    # (``default="processing"`` is Python-side only).
    op.add_column(
        "hotel_documents",
        sa.Column("status", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "hotel_documents",
        sa.Column("error", sa.Text(), nullable=True),
    )
    # Pre-queue documents were ingested synchronously, so their chunks are
    # already persisted: they are "ready", not "processing".
    op.execute("UPDATE hotel_documents SET status = 'ready' WHERE status IS NULL")
    op.alter_column(
        "hotel_documents",
        "status",
        existing_type=sa.String(length=20),
        nullable=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("hotel_documents", "error")
    op.drop_column("hotel_documents", "status")
