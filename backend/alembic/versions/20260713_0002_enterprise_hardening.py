"""Enterprise authentication, invariants, worker health, and tenant RLS.

Revision ID: 20260713_0002
"""

import sqlalchemy as sa
from alembic import op

revision = "20260713_0002"
down_revision = "20260713_0001"
branch_labels = None
depends_on = None

timestamp = sa.DateTime(timezone=True)
user_role = sa.Enum(
    "owner",
    "admin",
    "member",
    "viewer",
    name="user_role",
    native_enum=False,
    create_constraint=True,
    length=20,
)

TENANT_TABLES = (
    "projects",
    "audits",
    "audit_pages",
    "audit_prompts",
    "findings",
    "recommendations",
    "audit_events",
    "audit_rate_attempts",
)

RLS_EXPRESSION = """
    org_id = NULLIF(current_setting('app.current_org_id', true), '')
"""


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("role", user_role, nullable=False, server_default="member"),
    )
    op.add_column(
        "users",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column("users", sa.Column("oidc_issuer", sa.String(512)))
    op.add_column("users", sa.Column("oidc_subject", sa.String(255)))
    op.create_unique_constraint("uq_users_org_id", "users", ["org_id", "id"])
    op.create_unique_constraint("uq_users_oidc_identity", "users", ["oidc_issuer", "oidc_subject"])

    op.create_table(
        "user_sessions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column("user_id", sa.String(32), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("auth_method", sa.String(20), nullable=False),
        sa.Column("ip_address", sa.String(45)),
        sa.Column("user_agent", sa.String(512)),
        sa.Column("created_at", timestamp, nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", timestamp, nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", timestamp, nullable=False),
        sa.Column("revoked_at", timestamp),
        sa.ForeignKeyConstraint(
            ["org_id", "user_id"],
            ["users.org_id", "users.id"],
            name="fk_user_sessions_tenant_user",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_user_sessions_org_id", "user_sessions", ["org_id"])
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])
    op.create_index("ix_user_sessions_token_hash", "user_sessions", ["token_hash"], unique=True)
    op.create_index(
        "ix_user_sessions_user_active",
        "user_sessions",
        ["org_id", "user_id", "revoked_at", "expires_at"],
    )
    op.create_index("ix_user_sessions_expiry", "user_sessions", ["expires_at"])

    op.create_table(
        "security_audit_events",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("org_id", sa.String(32)),
        sa.Column("user_id", sa.String(32)),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("ip_address", sa.String(45)),
        sa.Column("user_agent", sa.String(512)),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", timestamp, nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["org_id", "user_id"],
            ["users.org_id", "users.id"],
            name="fk_security_events_tenant_user",
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_security_events_org_created",
        "security_audit_events",
        ["org_id", "created_at", "id"],
    )
    op.create_index(
        "ix_security_events_action_created",
        "security_audit_events",
        ["action", "created_at"],
    )

    op.create_table(
        "worker_heartbeats",
        sa.Column("worker_id", sa.String(80), primary_key=True),
        sa.Column("started_at", timestamp, nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", timestamp, nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_worker_heartbeats_last_seen_at",
        "worker_heartbeats",
        ["last_seen_at"],
    )

    op.create_check_constraint(
        "ck_audits_status_payload",
        "audits",
        "(status = 'queued' AND visibility_score IS NULL AND error_message IS NULL) OR "
        "(status = 'processing' AND visibility_score IS NULL) OR "
        "(status = 'completed' AND visibility_score IS NOT NULL AND error_message IS NULL) OR "
        "(status = 'failed' AND visibility_score IS NULL AND error_message IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_audits_lease_pair",
        "audits",
        "(worker_id IS NULL AND locked_at IS NULL) OR "
        "(worker_id IS NOT NULL AND locked_at IS NOT NULL)",
    )

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table in TENANT_TABLES:
            op.execute(sa.text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY'))
            op.execute(sa.text(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY'))
            op.execute(
                sa.text(
                    f'CREATE POLICY tenant_isolation ON "{table}" '
                    f"USING ({RLS_EXPRESSION}) WITH CHECK ({RLS_EXPRESSION})"
                )
            )
        op.execute(
            sa.text(
                """
                DO $grant$
                BEGIN
                    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'visibility_app') THEN
                        EXECUTE 'GRANT USAGE ON SCHEMA public TO visibility_app';
                        EXECUTE 'GRANT SELECT ON organizations, users TO visibility_app';
                        EXECUTE 'GRANT UPDATE (oidc_issuer, oidc_subject) ON users TO visibility_app';
                        EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON user_sessions TO visibility_app';
                        EXECUTE 'GRANT INSERT ON security_audit_events TO visibility_app';
                        EXECUTE 'GRANT SELECT, INSERT ON projects, audits TO visibility_app';
                        EXECUTE 'GRANT SELECT, INSERT, DELETE ON audit_rate_attempts TO visibility_app';
                        EXECUTE 'GRANT SELECT ON audit_pages, audit_prompts, findings TO visibility_app';
                        EXECUTE 'GRANT SELECT, INSERT ON audit_events TO visibility_app';
                        EXECUTE 'GRANT SELECT ON recommendations TO visibility_app';
                        EXECUTE 'GRANT UPDATE (status, updated_at) ON recommendations TO visibility_app';
                    END IF;
                    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'visibility_worker') THEN
                        EXECUTE 'GRANT USAGE ON SCHEMA public TO visibility_worker';
                        EXECUTE 'GRANT SELECT ON projects, audits TO visibility_worker';
                        EXECUTE 'GRANT INSERT, UPDATE, SELECT ON audits TO visibility_worker';
                        EXECUTE 'GRANT INSERT, SELECT ON audit_pages, audit_prompts, findings, recommendations, audit_events TO visibility_worker';
                        EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON worker_heartbeats TO visibility_worker';
                    END IF;
                END
                $grant$;
                """
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table in reversed(TENANT_TABLES):
            op.execute(sa.text(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"'))
            op.execute(sa.text(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY'))
            op.execute(sa.text(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY'))

    op.drop_constraint("ck_audits_lease_pair", "audits", type_="check")
    op.drop_constraint("ck_audits_status_payload", "audits", type_="check")
    op.drop_table("worker_heartbeats")
    op.drop_table("security_audit_events")
    op.drop_table("user_sessions")
    op.drop_constraint("uq_users_oidc_identity", "users", type_="unique")
    op.drop_constraint("uq_users_org_id", "users", type_="unique")
    op.drop_column("users", "oidc_subject")
    op.drop_column("users", "oidc_issuer")
    op.drop_column("users", "is_active")
    op.drop_column("users", "role")
