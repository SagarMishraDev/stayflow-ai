"""audit logs cascade on hotel delete

Revision ID: 3d4e5f6a7b8c
Revises: 99f111734fcd
Create Date: 2026-09-29 12:00:00.000000

Audit rows are scoped to a hotel's lifecycle: staff-management actions
(hotel_user.created/updated/deleted, super_admin.cross_hotel_access, ...)
write audit rows that reference the hotel. Without CASCADE, deleting a
hotel is blocked by its own audit history even after every operational
record is gone.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3d4e5f6a7b8c"
down_revision: str | Sequence[str] | None = "99f111734fcd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint("audit_logs_hotel_id_fkey", "audit_logs", type_="foreignkey")
    op.create_foreign_key(
        "audit_logs_hotel_id_fkey",
        "audit_logs",
        "hotels",
        ["hotel_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("audit_logs_hotel_id_fkey", "audit_logs", type_="foreignkey")
    op.create_foreign_key(
        "audit_logs_hotel_id_fkey",
        "audit_logs",
        "hotels",
        ["hotel_id"],
        ["id"],
    )
