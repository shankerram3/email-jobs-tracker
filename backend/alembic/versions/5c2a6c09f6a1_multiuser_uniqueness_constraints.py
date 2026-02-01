"""multiuser uniqueness constraints

Revision ID: 5c2a6c09f6a1
Revises: 18dfc5af22aa
Create Date: 2026-02-01

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "5c2a6c09f6a1"
down_revision: Union[str, None] = "18dfc5af22aa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = set(inspector.get_table_names())

    # ----------------------------
    # De-dupe rows before adding UNIQUE constraints
    # ----------------------------
    if "sync_state" in tables:
        # Keep the latest row per user_id (and keep one row for NULL user_id if present).
        op.execute(
            sa.text(
                """
                DELETE FROM sync_state
                WHERE id NOT IN (
                  SELECT MAX(id) FROM sync_state GROUP BY user_id
                )
                """
            )
        )

    if "reprocess_state" in tables:
        op.execute(
            sa.text(
                """
                DELETE FROM reprocess_state
                WHERE id NOT IN (
                  SELECT MAX(id) FROM reprocess_state GROUP BY user_id
                )
                """
            )
        )

    if "email_logs" in tables:
        # Remove duplicates per (user_id, gmail_message_id) so we can add a unique index.
        op.execute(
            sa.text(
                """
                DELETE FROM email_logs
                WHERE id NOT IN (
                  SELECT MAX(id)
                  FROM email_logs
                  GROUP BY user_id, gmail_message_id
                )
                """
            )
        )

    # ----------------------------
    # Add uniqueness constraints
    # ----------------------------
    if "sync_state" in tables:
        indexes = {i["name"] for i in inspector.get_indexes("sync_state")}
        if "ux_sync_state_user_id" not in indexes:
            op.create_index("ux_sync_state_user_id", "sync_state", ["user_id"], unique=True)

    if "reprocess_state" in tables:
        indexes = {i["name"] for i in inspector.get_indexes("reprocess_state")}
        if "ux_reprocess_state_user_id" not in indexes:
            op.create_index("ux_reprocess_state_user_id", "reprocess_state", ["user_id"], unique=True)

    if "email_logs" in tables:
        indexes = {i["name"] for i in inspector.get_indexes("email_logs")}
        if "ux_email_logs_user_gmail" not in indexes:
            op.create_index("ux_email_logs_user_gmail", "email_logs", ["user_id", "gmail_message_id"], unique=True)


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = set(inspector.get_table_names())

    if "email_logs" in tables:
        op.drop_index("ux_email_logs_user_gmail", table_name="email_logs", if_exists=True)

    if "reprocess_state" in tables:
        op.drop_index("ux_reprocess_state_user_id", table_name="reprocess_state", if_exists=True)

    if "sync_state" in tables:
        op.drop_index("ux_sync_state_user_id", table_name="sync_state", if_exists=True)

