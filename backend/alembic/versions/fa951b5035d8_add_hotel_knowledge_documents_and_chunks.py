"""add hotel knowledge documents and chunks

Revision ID: fa951b5035d8
Revises: cedfb3d5506c
Create Date: 2026-09-29 06:56:22.694825

Adds the two tables backing the hotel-knowledge RAG subsystem:
``hotel_documents`` (logical documents, hotel-scoped) and
``hotel_document_chunks`` (overlapping text chunks + JSON embeddings,
hotel-scoped). Reviewed by hand: only these two tables, nothing else.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "fa951b5035d8"
down_revision: str | Sequence[str] | None = "cedfb3d5506c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "hotel_documents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("hotel_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["hotel_id"],
            ["hotels.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_hotel_documents_hotel_id"), "hotel_documents", ["hotel_id"], unique=False
    )
    op.create_table(
        "hotel_document_chunks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("hotel_id", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["hotel_documents.id"],
        ),
        sa.ForeignKeyConstraint(
            ["hotel_id"],
            ["hotels.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_hotel_document_chunks_hotel_document",
        "hotel_document_chunks",
        ["hotel_id", "document_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_hotel_document_chunks_hotel_id"),
        "hotel_document_chunks",
        ["hotel_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_hotel_document_chunks_hotel_id"), table_name="hotel_document_chunks")
    op.drop_index("ix_hotel_document_chunks_hotel_document", table_name="hotel_document_chunks")
    op.drop_table("hotel_document_chunks")
    op.drop_index(op.f("ix_hotel_documents_hotel_id"), table_name="hotel_documents")
    op.drop_table("hotel_documents")
