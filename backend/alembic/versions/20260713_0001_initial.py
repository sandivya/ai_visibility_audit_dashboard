"""Initial tenant-safe visibility schema.

Revision ID: 20260713_0001
"""

import sqlalchemy as sa
from alembic import op

revision = "20260713_0001"
down_revision = None
branch_labels = None
depends_on = None

timestamp = sa.DateTime(timezone=True)
audit_status = sa.Enum(
    "queued",
    "processing",
    "completed",
    "failed",
    name="audit_status",
    native_enum=False,
    create_constraint=True,
    length=20,
)
recommendation_status = sa.Enum(
    "open",
    "in_progress",
    "completed",
    "dismissed",
    name="recommendation_status",
    native_enum=False,
    create_constraint=True,
    length=20,
)
audit_event_type = sa.Enum(
    "audit_created",
    "audit_started",
    "audit_retried",
    "page_analyzed",
    "prompt_checked",
    "finding_created",
    "recommendation_created",
    "audit_retry_scheduled",
    "audit_completed",
    "audit_failed",
    name="audit_event_type",
    native_enum=False,
    create_constraint=True,
    length=40,
)


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("created_at", timestamp, nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("created_at", timestamp, nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_users_org_id", "users", ["org_id"])
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "projects",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("domain", sa.String(253), nullable=False),
        sa.Column("competitors", sa.JSON(), nullable=False),
        sa.Column("created_at", timestamp, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", timestamp, nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("org_id", "id", name="uq_projects_org_id"),
    )
    op.create_index("ix_projects_org_id", "projects", ["org_id"])
    op.create_index("ix_projects_org_created_id", "projects", ["org_id", "created_at", "id"])

    op.create_table(
        "audits",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column("project_id", sa.String(32), nullable=False),
        sa.Column("status", audit_status, nullable=False),
        sa.Column("visibility_score", sa.Integer()),
        sa.Column("error_message", sa.Text()),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_at", timestamp, nullable=False, server_default=sa.func.now()),
        sa.Column("locked_at", timestamp),
        sa.Column("worker_id", sa.String(80)),
        sa.Column("created_at", timestamp, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", timestamp, nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["org_id", "project_id"],
            ["projects.org_id", "projects.id"],
            name="fk_audits_tenant_project",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("org_id", "id", name="uq_audits_org_id"),
        sa.UniqueConstraint("org_id", "project_id", "idempotency_key", name="uq_audit_idempotency"),
        sa.CheckConstraint(
            "visibility_score IS NULL OR (visibility_score >= 0 AND visibility_score <= 100)",
            name="ck_audits_visibility_score",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_audits_attempt_count"),
    )
    op.create_index("ix_audits_org_id", "audits", ["org_id"])
    op.create_index("ix_audits_project_id", "audits", ["project_id"])
    op.create_index(
        "ix_audits_org_project_created_id",
        "audits",
        ["org_id", "project_id", "created_at", "id"],
    )
    op.create_index("ix_audits_worker_queue", "audits", ["status", "available_at", "locked_at"])

    op.create_table(
        "audit_pages",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column("audit_id", sa.String(32), nullable=False),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("created_at", timestamp, nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["org_id", "audit_id"],
            ["audits.org_id", "audits.id"],
            name="fk_audit_pages_tenant_audit",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_audit_pages_audit_id", "audit_pages", ["audit_id"])
    op.create_index(
        "ix_audit_pages_org_audit_created",
        "audit_pages",
        ["org_id", "audit_id", "created_at"],
    )

    op.create_table(
        "audit_prompts",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column("audit_id", sa.String(32), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("mentioned_brand", sa.Boolean(), nullable=False),
        sa.Column("competitors_mentioned", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(80), nullable=False),
        sa.Column("created_at", timestamp, nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["org_id", "audit_id"],
            ["audits.org_id", "audits.id"],
            name="fk_audit_prompts_tenant_audit",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_audit_prompts_audit_id", "audit_prompts", ["audit_id"])
    op.create_index(
        "ix_audit_prompts_org_audit_created",
        "audit_prompts",
        ["org_id", "audit_id", "created_at"],
    )

    op.create_table(
        "findings",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column("audit_id", sa.String(32), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("category", sa.String(60), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("created_at", timestamp, nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["org_id", "audit_id"],
            ["audits.org_id", "audits.id"],
            name="fk_findings_tenant_audit",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_findings_audit_id", "findings", ["audit_id"])
    op.create_index(
        "ix_findings_org_audit_created",
        "findings",
        ["org_id", "audit_id", "created_at"],
    )
    op.create_index(
        "ix_findings_org_severity_category",
        "findings",
        ["org_id", "severity", "category", "created_at"],
    )

    op.create_table(
        "recommendations",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column("audit_id", sa.String(32), nullable=False),
        sa.Column("priority", sa.String(20), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", recommendation_status, nullable=False, server_default="open"),
        sa.Column("created_at", timestamp, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", timestamp, nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["org_id", "audit_id"],
            ["audits.org_id", "audits.id"],
            name="fk_recommendations_tenant_audit",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_recommendations_audit_id", "recommendations", ["audit_id"])
    op.create_index(
        "ix_recommendations_org_audit_created",
        "recommendations",
        ["org_id", "audit_id", "created_at"],
    )
    op.create_index(
        "ix_recommendations_org_status",
        "recommendations",
        ["org_id", "status", "updated_at"],
    )

    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column("audit_id", sa.String(32), nullable=False),
        sa.Column("event_type", audit_event_type, nullable=False),
        sa.Column("message", sa.String(255), nullable=False),
        sa.Column("created_at", timestamp, nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["org_id", "audit_id"],
            ["audits.org_id", "audits.id"],
            name="fk_audit_events_tenant_audit",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_audit_events_audit_id", "audit_events", ["audit_id"])
    op.create_index(
        "ix_events_org_audit_created",
        "audit_events",
        ["org_id", "audit_id", "created_at"],
    )

    op.create_table(
        "audit_rate_attempts",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column("created_at", timestamp, nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_audit_rate_attempts_org_id", "audit_rate_attempts", ["org_id"])
    op.create_index("ix_rate_org_created", "audit_rate_attempts", ["org_id", "created_at"])


def downgrade() -> None:
    op.drop_table("audit_rate_attempts")
    op.drop_table("audit_events")
    op.drop_table("recommendations")
    op.drop_table("findings")
    op.drop_table("audit_prompts")
    op.drop_table("audit_pages")
    op.drop_table("audits")
    op.drop_table("projects")
    op.drop_table("users")
    op.drop_table("organizations")
