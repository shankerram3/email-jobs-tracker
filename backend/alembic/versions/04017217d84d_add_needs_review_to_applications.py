"""add needs_review to applications

Revision ID: 04017217d84d
Revises: 01443ad4ce63
Create Date: 2026-02-01 12:32:29.678270

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '04017217d84d'
down_revision: Union[str, None] = '01443ad4ce63'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "applications" not in inspector.get_table_names():
        return

    cols = {c["name"] for c in inspector.get_columns("applications")}
    if "needs_review" in cols:
        return

    # Default low-confidence review flag to false for existing rows.
    dialect = conn.dialect.name
    if dialect == "sqlite":
        server_default = sa.text("0")
    else:
        server_default = sa.text("false")

    op.add_column(
        "applications",
        sa.Column("needs_review", sa.Boolean(), nullable=True, server_default=server_default),
    )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "applications" not in inspector.get_table_names():
        return
    cols = {c["name"] for c in inspector.get_columns("applications")}
    if "needs_review" in cols:
        op.drop_column("applications", "needs_review")
