from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import Settings

EXPECTED_SCHEMA_REVISION = "20260713_0003"
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


class SchemaNotReady(RuntimeError):
    pass


def verify_database_readiness(db: Session, settings: Settings) -> None:
    """Fail closed when the running application and database schema disagree."""
    try:
        db.execute(text("SELECT 1"))
        dialect = db.get_bind().dialect.name
        if dialect != "postgresql":
            tables = set(inspect(db.get_bind()).get_table_names())
            required = {"projects", "audits", "worker_heartbeats"}
            if not required.issubset(tables):
                raise SchemaNotReady("Required database tables are missing")
            return

        revision = db.scalar(text("SELECT version_num FROM alembic_version LIMIT 1"))
        if revision != EXPECTED_SCHEMA_REVISION:
            raise SchemaNotReady("Database migrations are not at the expected revision")

        secured_tables = int(
            db.scalar(
                text(
                    """
                    SELECT count(*)
                    FROM pg_class AS table_info
                    JOIN pg_namespace AS namespace
                      ON namespace.oid = table_info.relnamespace
                    WHERE namespace.nspname = current_schema()
                      AND table_info.relname = ANY(:tables)
                      AND table_info.relrowsecurity
                      AND table_info.relforcerowsecurity
                    """
                ),
                {"tables": list(TENANT_TABLES)},
            )
            or 0
        )
        policy_count = int(
            db.scalar(
                text(
                    """
                    SELECT count(*)
                    FROM pg_policies
                    WHERE schemaname = current_schema()
                      AND tablename = ANY(:tables)
                      AND policyname = 'tenant_isolation'
                      AND qual IS NOT NULL
                      AND with_check IS NOT NULL
                    """
                ),
                {"tables": list(TENANT_TABLES)},
            )
            or 0
        )
        if secured_tables != len(TENANT_TABLES) or policy_count != len(TENANT_TABLES):
            raise SchemaNotReady("Tenant row-level security is not fully enabled")

        tenant_context = db.scalar(
            text("SELECT NULLIF(current_setting('app.current_org_id', true), '')")
        )
        if tenant_context is not None:
            raise SchemaNotReady("Readiness connection unexpectedly has tenant context")

        if settings.app_env == "production":
            role = db.execute(
                text(
                    """
                    SELECT rolsuper, rolbypassrls
                    FROM pg_roles
                    WHERE rolname = current_user
                    """
                )
            ).one_or_none()
            if role is None or bool(role.rolsuper) or bool(role.rolbypassrls):
                raise SchemaNotReady("The API database role can bypass tenant isolation")
    except SchemaNotReady:
        raise
    except SQLAlchemyError as exc:
        raise SchemaNotReady("Database readiness verification failed") from exc
