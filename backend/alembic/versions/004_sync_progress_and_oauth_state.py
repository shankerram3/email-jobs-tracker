"""Add sync progress columns and oauth_state table for persisted state.

Revision ID: 004_sync_oauth
Revises: 003_email_logs_user
Create Date: 2025-01-28

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "004_sync_oauth"
down_revision: Union[str, None] = "003_email_logs_user"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    is_sqlite = conn.dialect.name == "sqlite"

    # sync_state: add processed, total, message, created, skipped, errors
    if "sync_state" in inspector.get_table_names():
        cols = {c["name"] for c in inspector.get_columns("sync_state")}
        if "processed" not in cols:
            op.add_column("sync_state", sa.Column("processed", sa.Integer(), nullable=True))
        if "total" not in cols:
            op.add_column("sync_state", sa.Column("total", sa.Integer(), nullable=True))
        if "message" not in cols:
            op.add_column("sync_state", sa.Column("message", sa.String(255), nullable=True))
        if "created" not in cols:
            op.add_column("sync_state", sa.Column("created", sa.Integer(), nullable=True))
        if "skipped" not in cols:
            op.add_column("sync_state", sa.Column("skipped", sa.Integer(), nullable=True))
        if "errors" not in cols:
            op.add_column("sync_state", sa.Column("errors", sa.Integer(), nullable=True))

    # oauth_state table for Gmail and Google Sign-in CSRF state
    if "oauth_state" not in inspector.get_table_names():
        op.create_table(
            "oauth_state",
            sa.Column("state_token", sa.String(64), primary_key=True),
            sa.Column("kind", sa.String(32), nullable=False),
            sa.Column("redirect_url", sa.String(512), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index(op.f("ix_oauth_state_kind"), "oauth_state", ["kind"], unique=False)


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if "oauth_state" in inspector.get_table_names():
        op.drop_index(op.f("ix_oauth_state_kind"), table_name="oauth_state")
        op.drop_table("oauth_state")

    if "sync_state" in inspector.get_table_names():
        cols = {c["name"] for c in inspector.get_columns("sync_state")}
        if "errors" in cols:
            op.drop_column("sync_state", "errors")
        if "skipped" in cols:
            op.drop_column("sync_state", "skipped")
        if "created" in cols:
            op.drop_column("sync_state", "created")
        if "message" in cols:
            op.drop_column("sync_state", "message")
        if "total" in cols:
            op.drop_column("sync_state", "total")
        if "processed" in cols:
            op.drop_column("sync_state", "processed")
