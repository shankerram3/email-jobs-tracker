"""Schema upgrades: applications new fields, sync_state, companies, classification_cache.

Revision ID: 001_schema
Revises:
Create Date: 2025-01-28

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # sync_state table
    op.create_table(
        "sync_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("last_history_id", sa.String(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.Column("last_full_sync_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_sync_state_id"), "sync_state", ["id"], unique=False)

    # companies table
    op.create_table(
        "companies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("canonical_name", sa.String(), nullable=False),
        sa.Column("aliases", sa.JSON(), nullable=True),
        sa.Column("industry", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_companies_canonical_name"), "companies", ["canonical_name"], unique=True)
    op.create_index(op.f("ix_companies_id"), "companies", ["id"], unique=False)

    # classification_cache table
    op.create_table(
        "classification_cache",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("subcategory", sa.String(), nullable=True),
        sa.Column("company_name", sa.String(), nullable=True),
        sa.Column("job_title", sa.String(), nullable=True),
        sa.Column("salary_min", sa.Float(), nullable=True),
        sa.Column("salary_max", sa.Float(), nullable=True),
        sa.Column("location", sa.String(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("raw_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_classification_cache_content_hash"), "classification_cache", ["content_hash"], unique=True)
    op.create_index(op.f("ix_classification_cache_id"), "classification_cache", ["id"], unique=False)

    # Add new columns to applications (if table exists)
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "applications" in inspector.get_table_names():
        cols = {c["name"] for c in inspector.get_columns("applications")}
        if "subcategory" not in cols:
            op.add_column("applications", sa.Column("subcategory", sa.String(), nullable=True))
        if "job_title" not in cols:
            op.add_column("applications", sa.Column("job_title", sa.String(), nullable=True))
        if "salary_min" not in cols:
            op.add_column("applications", sa.Column("salary_min", sa.Float(), nullable=True))
        if "salary_max" not in cols:
            op.add_column("applications", sa.Column("salary_max", sa.Float(), nullable=True))
        if "location" not in cols:
            op.add_column("applications", sa.Column("location", sa.String(), nullable=True))
        if "confidence" not in cols:
            op.add_column("applications", sa.Column("confidence", sa.Float(), nullable=True))
        if "applied_at" not in cols:
            op.add_column("applications", sa.Column("applied_at", sa.DateTime(), nullable=True))
        if "rejected_at" not in cols:
            op.add_column("applications", sa.Column("rejected_at", sa.DateTime(), nullable=True))
        if "interview_at" not in cols:
            op.add_column("applications", sa.Column("interview_at", sa.DateTime(), nullable=True))
        if "offer_at" not in cols:
            op.add_column("applications", sa.Column("offer_at", sa.DateTime(), nullable=True))
        if "linkedin_url" not in cols:
            op.add_column("applications", sa.Column("linkedin_url", sa.String(), nullable=True))

    # Create indexes on applications (idempotent: check if index exists)
    try:
        op.create_index("ix_applications_category_received_date", "applications", ["category", "received_date"], unique=False)
    except Exception:
        pass
    try:
        op.create_index("ix_applications_status_received_date", "applications", ["status", "received_date"], unique=False)
    except Exception:
        pass
    try:
        op.create_index("ix_applications_received_date", "applications", ["received_date"], unique=False)
    except Exception:
        pass


def downgrade() -> None:
    op.drop_index("ix_applications_received_date", table_name="applications", if_exists=True)
    op.drop_index("ix_applications_status_received_date", table_name="applications", if_exists=True)
    op.drop_index("ix_applications_category_received_date", table_name="applications", if_exists=True)

    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "applications" in inspector.get_table_names():
        cols = {c["name"] for c in inspector.get_columns("applications")}
        for col in ("linkedin_url", "offer_at", "interview_at", "rejected_at", "applied_at", "confidence", "location", "salary_max", "salary_min", "job_title", "subcategory"):
            if col in cols:
                op.drop_column("applications", col)

    op.drop_index(op.f("ix_classification_cache_content_hash"), table_name="classification_cache")
    op.drop_index(op.f("ix_classification_cache_id"), table_name="classification_cache")
    op.drop_table("classification_cache")
    op.drop_index(op.f("ix_companies_canonical_name"), table_name="companies")
    op.drop_index(op.f("ix_companies_id"), table_name="companies")
    op.drop_table("companies")
    op.drop_index(op.f("ix_sync_state_id"), table_name="sync_state")
    op.drop_table("sync_state")
