"""Add user_id to oauth_state.

Revision ID: 7f21c1e9d2aa
Revises: 6b3f0f2a9b1c
Create Date: 2026-02-01
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "7f21c1e9d2aa"
down_revision: Union[str, None] = "6b3f0f2a9b1c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = set(inspector.get_table_names())

    if "oauth_state" not in tables:
        return

    columns = {c["name"] for c in inspector.get_columns("oauth_state")}
    if "user_id" not in columns:
        op.add_column(
            "oauth_state",
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        )

    existing_indexes = {ix["name"] for ix in inspector.get_indexes("oauth_state")}
    if "ix_oauth_state_user_id" not in existing_indexes:
        op.create_index("ix_oauth_state_user_id", "oauth_state", ["user_id"], unique=False)


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = set(inspector.get_table_names())

    if "oauth_state" not in tables:
        return

    existing_indexes = {ix["name"] for ix in inspector.get_indexes("oauth_state")}
    if "ix_oauth_state_user_id" in existing_indexes:
        op.drop_index("ix_oauth_state_user_id", table_name="oauth_state")

    columns = {c["name"] for c in inspector.get_columns("oauth_state")}
    if "user_id" in columns:
        op.drop_column("oauth_state", "user_id")

