"""Add users table, user_id to applications and sync_state, create default user and assign existing data.

Revision ID: 002_users
Revises: 001_schema
Create Date: 2025-01-28

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import bcrypt

revision: str = "002_users"
down_revision: Union[str, None] = "001_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_EMAIL = "ramsankarharikrishnan@gmail.com"
DEFAULT_PASSWORD = "password"


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    # Create users table if it doesn't exist (idempotent: may have been created by init_db)
    if "users" not in inspector.get_table_names():
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("email", sa.String(), nullable=False),
            sa.Column("password_hash", sa.String(), nullable=True),
            sa.Column("google_id", sa.String(), nullable=True),
            sa.Column("name", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_users_id"), "users", ["id"], unique=False)
        op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
        op.create_index(op.f("ix_users_google_id"), "users", ["google_id"], unique=False)

    is_sqlite = conn.dialect.name == "sqlite"

    # Add user_id to applications if missing (SQLite: no FK via ALTER)
    if "applications" in inspector.get_table_names():
        app_cols = {c["name"] for c in inspector.get_columns("applications")}
        if "user_id" not in app_cols:
            op.add_column("applications", sa.Column("user_id", sa.Integer(), nullable=True))
            if not is_sqlite:
                op.create_foreign_key(
                    "fk_applications_user_id",
                    "applications",
                    "users",
                    ["user_id"],
                    ["id"],
                    ondelete="CASCADE",
                )
            try:
                op.create_index(op.f("ix_applications_user_id"), "applications", ["user_id"], unique=False)
            except Exception:
                pass
    try:
        op.create_index(
            "ix_applications_user_gmail",
            "applications",
            ["user_id", "gmail_message_id"],
            unique=True,
        )
    except Exception:
        pass

    # Add user_id to sync_state if missing (SQLite: no FK via ALTER)
    if "sync_state" in inspector.get_table_names():
        sync_cols = {c["name"] for c in inspector.get_columns("sync_state")}
        if "user_id" not in sync_cols:
            op.add_column("sync_state", sa.Column("user_id", sa.Integer(), nullable=True))
            if not is_sqlite:
                op.create_foreign_key(
                    "fk_sync_state_user_id",
                    "sync_state",
                    "users",
                    ["user_id"],
                    ["id"],
                    ondelete="CASCADE",
                )
            try:
                op.create_index(op.f("ix_sync_state_user_id"), "sync_state", ["user_id"], unique=False)
            except Exception:
                pass

    # Create default user if not exists
    result = conn.execute(sa.text("SELECT id FROM users WHERE email = :email"), {"email": DEFAULT_EMAIL})
    row = result.fetchone()
    if not row:
        password_hash = _hash_password(DEFAULT_PASSWORD)
        conn.execute(
            sa.text(
                "INSERT INTO users (email, password_hash, created_at, updated_at) "
                "VALUES (:email, :password_hash, datetime('now'), datetime('now'))"
            ),
            {"email": DEFAULT_EMAIL, "password_hash": password_hash},
        )
        result = conn.execute(sa.text("SELECT id FROM users WHERE email = :email"), {"email": DEFAULT_EMAIL})
        row = result.fetchone()
    user_id = row[0] if row else 1

    # Assign all existing applications and sync_state rows to this user (where user_id is null)
    conn.execute(sa.text("UPDATE applications SET user_id = :uid WHERE user_id IS NULL"), {"uid": user_id})
    conn.execute(sa.text("UPDATE sync_state SET user_id = :uid WHERE user_id IS NULL"), {"uid": user_id})


def downgrade() -> None:
    conn = op.get_bind()
    is_sqlite = conn.dialect.name == "sqlite"

    op.drop_index("ix_applications_user_gmail", table_name="applications")
    op.drop_index(op.f("ix_sync_state_user_id"), table_name="sync_state")
    # Only drop FKs if they exist (non-SQLite); upgrade skips creating them on SQLite
    if not is_sqlite:
        op.drop_constraint("fk_sync_state_user_id", "sync_state", type_="foreignkey")
    op.drop_column("sync_state", "user_id")
    op.drop_index(op.f("ix_applications_user_id"), table_name="applications")
    if not is_sqlite:
        op.drop_constraint("fk_applications_user_id", "applications", type_="foreignkey")
    op.drop_column("applications", "user_id")
    op.drop_index(op.f("ix_users_google_id"), table_name="users")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_index(op.f("ix_users_id"), table_name="users")
    op.drop_table("users")
