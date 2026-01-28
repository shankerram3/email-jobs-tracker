"""Add user_id to email_logs for per-user isolation.

Revision ID: 003_email_logs_user
Revises: 002_users
Create Date: 2025-01-28

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "003_email_logs_user"
down_revision: Union[str, None] = "002_users"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    is_sqlite = conn.dialect.name == "sqlite"

    if "email_logs" not in inspector.get_table_names():
        return
    cols = {c["name"] for c in inspector.get_columns("email_logs")}
    if "user_id" in cols:
        return

    op.add_column("email_logs", sa.Column("user_id", sa.Integer(), nullable=True))
    op.create_index(op.f("ix_email_logs_user_id"), "email_logs", ["user_id"], unique=False)
    if not is_sqlite:
        op.create_foreign_key(
            "fk_email_logs_user_id",
            "email_logs",
            "users",
            ["user_id"],
            ["id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    conn = op.get_bind()
    is_sqlite = conn.dialect.name == "sqlite"

    if not is_sqlite:
        op.drop_constraint("fk_email_logs_user_id", "email_logs", type_="foreignkey")
    op.drop_index(op.f("ix_email_logs_user_id"), table_name="email_logs")
    op.drop_column("email_logs", "user_id")
