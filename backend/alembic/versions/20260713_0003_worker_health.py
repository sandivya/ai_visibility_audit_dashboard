"""Add worker poll health and queue observations.

Revision ID: 20260713_0003
"""

import sqlalchemy as sa
from alembic import op

revision = "20260713_0003"
down_revision = "20260713_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    timestamp = sa.DateTime(timezone=True)
    op.add_column("worker_heartbeats", sa.Column("last_poll_at", timestamp))
    op.add_column("worker_heartbeats", sa.Column("last_progress_at", timestamp))
    op.add_column("worker_heartbeats", sa.Column("last_error_at", timestamp))
    op.add_column(
        "worker_heartbeats",
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "worker_heartbeats",
        sa.Column("queued_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "worker_heartbeats",
        sa.Column("processing_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "worker_heartbeats",
        sa.Column("retry_wait_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_worker_heartbeats_last_poll_at",
        "worker_heartbeats",
        ["last_poll_at"],
    )
    op.create_check_constraint(
        "ck_worker_failures_nonnegative",
        "worker_heartbeats",
        "consecutive_failures >= 0",
    )
    op.create_check_constraint(
        "ck_worker_queued_nonnegative",
        "worker_heartbeats",
        "queued_count >= 0",
    )
    op.create_check_constraint(
        "ck_worker_processing_nonnegative",
        "worker_heartbeats",
        "processing_count >= 0",
    )
    op.create_check_constraint(
        "ck_worker_retry_wait_nonnegative",
        "worker_heartbeats",
        "retry_wait_count >= 0",
    )

    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            sa.text(
                """
                DO $grant$
                BEGIN
                    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'visibility_app') THEN
                        EXECUTE 'GRANT SELECT ON alembic_version, worker_heartbeats TO visibility_app';
                    END IF;
                END
                $grant$;
                """
            )
        )


def downgrade() -> None:
    op.drop_constraint("ck_worker_retry_wait_nonnegative", "worker_heartbeats", type_="check")
    op.drop_constraint("ck_worker_processing_nonnegative", "worker_heartbeats", type_="check")
    op.drop_constraint("ck_worker_queued_nonnegative", "worker_heartbeats", type_="check")
    op.drop_constraint("ck_worker_failures_nonnegative", "worker_heartbeats", type_="check")
    op.drop_index("ix_worker_heartbeats_last_poll_at", table_name="worker_heartbeats")
    op.drop_column("worker_heartbeats", "retry_wait_count")
    op.drop_column("worker_heartbeats", "processing_count")
    op.drop_column("worker_heartbeats", "queued_count")
    op.drop_column("worker_heartbeats", "consecutive_failures")
    op.drop_column("worker_heartbeats", "last_error_at")
    op.drop_column("worker_heartbeats", "last_progress_at")
    op.drop_column("worker_heartbeats", "last_poll_at")
