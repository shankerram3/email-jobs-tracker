"""add reprocess_state table

Revision ID: 18dfc5af22aa
Revises: 04017217d84d
Create Date: 2026-02-01 12:38:08.392248

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '18dfc5af22aa'
down_revision: Union[str, None] = '04017217d84d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "reprocess_state" in inspector.get_table_names():
        return

    op.create_table(
        "reprocess_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("message", sa.String(length=255), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("processed", sa.Integer(), nullable=True),
        sa.Column("total", sa.Integer(), nullable=True),
        sa.Column("task_id", sa.String(length=128), nullable=True),
        sa.Column("params", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_reprocess_state_id"), "reprocess_state", ["id"], unique=False)
    op.create_index(op.f("ix_reprocess_state_task_id"), "reprocess_state", ["task_id"], unique=False)
    op.create_index(op.f("ix_reprocess_state_user_id"), "reprocess_state", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_reprocess_state_user_id"), table_name="reprocess_state", if_exists=True)
    op.drop_index(op.f("ix_reprocess_state_task_id"), table_name="reprocess_state", if_exists=True)
    op.drop_index(op.f("ix_reprocess_state_id"), table_name="reprocess_state", if_exists=True)
    op.drop_table("reprocess_state")
