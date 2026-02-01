"""add resumes table and backfill langgraph categories

Revision ID: 01443ad4ce63
Revises: 004_sync_oauth
Create Date: 2026-01-30 10:49:18.028130

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '01443ad4ce63'
down_revision: Union[str, None] = '004_sync_oauth'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    existing_tables = set(inspector.get_table_names())
    if "resumes" not in existing_tables:
        op.create_table(
            "resumes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("filename", sa.String(), nullable=False),
            sa.Column("drive_file_id", sa.String(), nullable=True),
            sa.Column("version", sa.String(), nullable=True),
            sa.Column("company", sa.String(), nullable=True),
            sa.Column("job_title", sa.String(), nullable=True),
            sa.Column("specialization", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )

    # Ensure expected indexes exist (idempotent without swallowing SQL errors).
    inspector = sa.inspect(conn)
    existing_indexes = {ix.get("name") for ix in inspector.get_indexes("resumes") if ix and ix.get("name")}

    def _create_index_if_missing(name: str, cols: list[str]) -> None:
        if name in existing_indexes:
            return
        op.create_index(name, "resumes", cols)

    _create_index_if_missing("ix_resumes_drive_file_id", ["drive_file_id"])
    _create_index_if_missing("ix_resumes_version", ["version"])
    _create_index_if_missing("ix_resumes_company", ["company"])
    _create_index_if_missing("ix_resumes_job_title", ["job_title"])
    _create_index_if_missing("ix_resumes_specialization", ["specialization"])

    # Backfill applications only if the table exists (fresh DBs may not have legacy rows).
    existing_tables = set(sa.inspect(conn).get_table_names())
    if "applications" in existing_tables:
        # Preserve legacy OFFER rows as Offer stage before we remap category.
        # (We keep 14 classes; offers are represented via application_stage='Offer'.)
        op.execute(
            """
            UPDATE applications
            SET application_stage = 'Offer',
                requires_action = TRUE,
                action_items = '["Review offer details and respond"]'::json
            WHERE category = 'OFFER'
            """
        )

        # Backfill legacy categories -> LangGraph 14-class taxonomy (stored in applications.category).
        # NOTE: We keep 14 classes; prior OFFER rows were staged above.
        op.execute(
            """
            UPDATE applications
            SET category = CASE category
                WHEN 'REJECTION' THEN 'job_rejection'
                WHEN 'INTERVIEW_REQUEST' THEN 'interview_assessment'
                WHEN 'SCREENING_REQUEST' THEN 'interview_assessment'
                WHEN 'ASSESSMENT' THEN 'interview_assessment'
                WHEN 'APPLICATION_RECEIVED' THEN 'job_application_confirmation'
                WHEN 'RECRUITER_OUTREACH' THEN 'recruiter_outreach'
                WHEN 'OFFER' THEN 'application_followup'
                ELSE category
            END
            WHERE category IN (
                'REJECTION',
                'INTERVIEW_REQUEST',
                'SCREENING_REQUEST',
                'ASSESSMENT',
                'APPLICATION_RECEIVED',
                'RECRUITER_OUTREACH',
                'OFFER'
            )
            """
        )

        # Backfill application_stage based on legacy category.
        op.execute(
            """
            UPDATE applications
            SET application_stage = CASE
                WHEN category = 'job_rejection' THEN 'Rejected'
                WHEN category = 'job_application_confirmation' THEN 'Applied'
                WHEN category = 'recruiter_outreach' THEN 'Contacted'
                WHEN category = 'interview_assessment' THEN 'Interview'
                WHEN category = 'application_followup' AND (application_stage IS NULL OR application_stage = '' OR application_stage = 'Other') THEN 'Applied'
                ELSE application_stage
            END
            """
        )


def downgrade() -> None:
    # Best-effort reverse mapping (lossy: offers were stored as stage only).
    op.execute(
        """
        UPDATE applications
        SET category = CASE category
            WHEN 'job_rejection' THEN 'REJECTION'
            WHEN 'interview_assessment' THEN 'INTERVIEW_REQUEST'
            WHEN 'job_application_confirmation' THEN 'APPLICATION_RECEIVED'
            WHEN 'recruiter_outreach' THEN 'RECRUITER_OUTREACH'
            ELSE category
        END
        """
    )
    op.drop_index("ix_resumes_specialization", table_name="resumes")
    op.drop_index("ix_resumes_job_title", table_name="resumes")
    op.drop_index("ix_resumes_company", table_name="resumes")
    op.drop_index("ix_resumes_version", table_name="resumes")
    op.drop_index("ix_resumes_drive_file_id", table_name="resumes")
    op.drop_table("resumes")
