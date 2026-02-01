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
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    def _index_exists(table_name: str, index_name: str) -> bool:
        return any(idx.get("name") == index_name for idx in inspector.get_indexes(table_name))

    table_names = set(inspector.get_table_names())

    # applications table (idempotent; needed for fresh Postgres DBs)
    if "applications" not in table_names:
        op.create_table(
            "applications",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("gmail_message_id", sa.String(), nullable=True),
            sa.Column("company_name", sa.String(), nullable=True),
            sa.Column("position", sa.String(), nullable=True),
            sa.Column("status", sa.String(), nullable=True),
            sa.Column("category", sa.String(), nullable=True),
            sa.Column("subcategory", sa.String(), nullable=True),
            sa.Column("job_title", sa.String(), nullable=True),
            sa.Column("salary_min", sa.Float(), nullable=True),
            sa.Column("salary_max", sa.Float(), nullable=True),
            sa.Column("location", sa.String(), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("email_subject", sa.String(), nullable=True),
            sa.Column("email_from", sa.String(), nullable=True),
            sa.Column("email_body", sa.Text(), nullable=True),
            sa.Column("received_date", sa.DateTime(), nullable=True),
            sa.Column("applied_at", sa.DateTime(), nullable=True),
            sa.Column("rejected_at", sa.DateTime(), nullable=True),
            sa.Column("interview_at", sa.DateTime(), nullable=True),
            sa.Column("offer_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.Column("linkedin_url", sa.String(), nullable=True),
            sa.Column("classification_reasoning", sa.Text(), nullable=True),
            sa.Column("position_level", sa.String(), nullable=True),
            sa.Column("application_stage", sa.String(), nullable=True),
            sa.Column("requires_action", sa.Boolean(), nullable=True),
            sa.Column("action_items", sa.JSON(), nullable=True),
            sa.Column("resume_matched", sa.String(), nullable=True),
            sa.Column("resume_file_id", sa.String(), nullable=True),
            sa.Column("resume_version", sa.String(), nullable=True),
            sa.Column("processing_status", sa.String(), nullable=True),
            sa.Column("processed_by", sa.String(), nullable=True),
            sa.Column("needs_review", sa.Boolean(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        table_names.add("applications")

    # email_logs table (idempotent; user_id is added in 003 migration)
    if "email_logs" not in table_names:
        op.create_table(
            "email_logs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("gmail_message_id", sa.String(), nullable=True),
            sa.Column("processed_at", sa.DateTime(), nullable=True),
            sa.Column("classification", sa.String(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        table_names.add("email_logs")

    # sync_metadata table (idempotent; used for backward compatibility)
    if "sync_metadata" not in table_names:
        op.create_table(
            "sync_metadata",
            sa.Column("key", sa.String(), nullable=False),
            sa.Column("value", sa.Text(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("key"),
        )
        table_names.add("sync_metadata")

    # sync_state table (idempotent)
    if "sync_state" not in table_names:
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
        table_names.add("sync_state")
    if "sync_state" in table_names:
        idx_name = op.f("ix_sync_state_id")
        if not _index_exists("sync_state", idx_name):
            op.create_index(idx_name, "sync_state", ["id"], unique=False)

    # companies table (idempotent)
    if "companies" not in table_names:
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
        table_names.add("companies")
    if "companies" in table_names:
        idx_canonical = op.f("ix_companies_canonical_name")
        if not _index_exists("companies", idx_canonical):
            op.create_index(idx_canonical, "companies", ["canonical_name"], unique=True)
        idx_id = op.f("ix_companies_id")
        if not _index_exists("companies", idx_id):
            op.create_index(idx_id, "companies", ["id"], unique=False)

    # classification_cache table (idempotent)
    if "classification_cache" not in table_names:
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
        table_names.add("classification_cache")
    if "classification_cache" in table_names:
        idx_hash = op.f("ix_classification_cache_content_hash")
        if not _index_exists("classification_cache", idx_hash):
            op.create_index(idx_hash, "classification_cache", ["content_hash"], unique=True)
        idx_id = op.f("ix_classification_cache_id")
        if not _index_exists("classification_cache", idx_id):
            op.create_index(idx_id, "classification_cache", ["id"], unique=False)

    # Add new columns to applications (if table exists)
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
        if "needs_review" not in cols:
            op.add_column("applications", sa.Column("needs_review", sa.Boolean(), nullable=True))

    # Create indexes on applications (idempotent: check if index exists)
    if "applications" in table_names:
        for idx_name, cols in (
            ("ix_applications_category_received_date", ["category", "received_date"]),
            ("ix_applications_status_received_date", ["status", "received_date"]),
            ("ix_applications_received_date", ["received_date"]),
        ):
            if not _index_exists("applications", idx_name):
                op.create_index(idx_name, "applications", cols, unique=False)


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
