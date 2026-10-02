"""allow anonymous conversations (nullable guest_id)

Revision ID: a1b2c3d4e5f6
Revises: f1a2b3c4d5e6
Create Date: 2026-09-29 00:00:00.000000

Web/Telegram guests may start chatting before they are identified, so
conversations.guest_id becomes nullable.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "f1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column("conversations", "guest_id", nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    # Anonymous conversations cannot be mapped back to a guest; remove them
    # (and their messages) rather than writing a bogus guest_id=0 that would
    # violate the guests foreign key.
    op.execute(
        sa.text(
            "DELETE FROM messages WHERE conversation_id IN "
            "(SELECT id FROM conversations WHERE guest_id IS NULL)"
        )
    )
    op.execute(sa.text("DELETE FROM conversations WHERE guest_id IS NULL"))
    op.alter_column("conversations", "guest_id", nullable=False)
