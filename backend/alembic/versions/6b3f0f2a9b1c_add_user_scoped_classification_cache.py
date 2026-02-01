"""Add user-scoped classification cache.

Revision ID: 6b3f0f2a9b1c
Revises: 5c2a6c09f6a1
Create Date: 2026-02-01
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "6b3f0f2a9b1c"
down_revision: Union[str, None] = "5c2a6c09f6a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = set(inspector.get_table_names())

    if "classification_cache" not in tables:
        return

    columns = {c["name"] for c in inspector.get_columns("classification_cache")}
    if "user_id" not in columns:
        op.add_column(
            "classification_cache",
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        )

    # Drop legacy unique constraint/index on content_hash (global) if present.
    for uc in inspector.get_unique_constraints("classification_cache"):
        if uc.get("column_names") == ["content_hash"]:
            op.drop_constraint(uc["name"], "classification_cache", type_="unique")
            break

    indexes = {i["name"] for i in inspector.get_indexes("classification_cache")}
    had_content_index = "ix_classification_cache_content_hash" in indexes
    if had_content_index:
        # Ensure it's non-unique. Drop and recreate if it was unique.
        op.drop_index("ix_classification_cache_content_hash", table_name="classification_cache")

    if had_content_index or "ix_classification_cache_content_hash" not in indexes:
        op.create_index(
            "ix_classification_cache_content_hash",
            "classification_cache",
            ["content_hash"],
            unique=False,
        )

    if "ix_classification_cache_user_id" not in indexes:
        op.create_index(
            "ix_classification_cache_user_id",
            "classification_cache",
            ["user_id"],
            unique=False,
        )

    if "ix_classification_cache_user_hash" not in indexes:
        op.create_index(
            "ix_classification_cache_user_hash",
            "classification_cache",
            ["user_id", "content_hash"],
            unique=True,
        )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = set(inspector.get_table_names())

    if "classification_cache" not in tables:
        return

    indexes = {i["name"] for i in inspector.get_indexes("classification_cache")}
    if "ix_classification_cache_user_hash" in indexes:
        op.drop_index("ix_classification_cache_user_hash", table_name="classification_cache")
    if "ix_classification_cache_user_id" in indexes:
        op.drop_index("ix_classification_cache_user_id", table_name="classification_cache")

    columns = {c["name"] for c in inspector.get_columns("classification_cache")}
    if "user_id" in columns:
        op.drop_column("classification_cache", "user_id")

    # Restore unique constraint on content_hash for legacy behavior.
    indexes = {i["name"] for i in inspector.get_indexes("classification_cache")}
    if "ix_classification_cache_content_hash" in indexes:
        op.drop_index("ix_classification_cache_content_hash", table_name="classification_cache")
    op.create_index(
        "ix_classification_cache_content_hash",
        "classification_cache",
        ["content_hash"],
        unique=True,
    )
