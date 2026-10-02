"""add opaque access tokens for public conversations

Revision ID: 7a8b9c0d1e2f
Revises: 6fac09f32444
Create Date: 2026-09-29 21:00:00.000000

Public web chat must not rely on guessable integer conversation IDs. Each
conversation receives a random capability token that is returned only to the
client that created/continued the conversation.
"""

import secrets
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "7a8b9c0d1e2f"
down_revision: str | Sequence[str] | None = "6fac09f32444"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("access_token", sa.String(length=64), nullable=True),
    )

    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id FROM conversations WHERE access_token IS NULL")
    ).fetchall()
    for (conversation_id,) in rows:
        bind.execute(
            sa.text("UPDATE conversations SET access_token = :token WHERE id = :id"),
            {"token": secrets.token_urlsafe(48), "id": conversation_id},
        )

    op.alter_column("conversations", "access_token", nullable=False)
    op.create_index(
        "ix_conversations_access_token",
        "conversations",
        ["access_token"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_conversations_access_token", table_name="conversations")
    op.drop_column("conversations", "access_token")
