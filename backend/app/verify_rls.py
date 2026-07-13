import os

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.database import set_tenant_context
from app.models import (
    Audit,
    AuditEvent,
    AuditPage,
    AuditPrompt,
    AuditRateAttempt,
    Finding,
    Project,
    Recommendation,
)
from app.schema_health import TENANT_TABLES

TENANT_MODELS = (
    Project,
    Audit,
    AuditPage,
    AuditPrompt,
    Finding,
    Recommendation,
    AuditEvent,
    AuditRateAttempt,
)


def _expect_rls_rejection(db: Session, row: object) -> None:
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except DBAPIError:
        return
    raise RuntimeError("PostgreSQL RLS WITH CHECK accepted a cross-tenant write")


def verify() -> None:
    database_url = os.environ.get("RLS_DATABASE_URL")
    if not database_url:
        raise RuntimeError("RLS_DATABASE_URL must use the restricted application role")
    engine = create_engine(database_url, pool_pre_ping=True)
    with Session(engine) as db:
        if db.get_bind().dialect.name != "postgresql":
            raise RuntimeError("RLS verification requires PostgreSQL")
        role = db.scalar(select(func.current_user()))
        if role != "visibility_app":
            raise RuntimeError("RLS verification must run as visibility_app")
        role_capabilities = db.execute(
            text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
        ).one()
        if bool(role_capabilities[0]) or bool(role_capabilities[1]):
            raise RuntimeError("The restricted API role can bypass RLS")

        policies = db.execute(
            text(
                """
                SELECT tablename, qual, with_check
                FROM pg_policies
                WHERE schemaname = current_schema()
                  AND policyname = 'tenant_isolation'
                  AND tablename = ANY(:tables)
                """
            ),
            {"tables": list(TENANT_TABLES)},
        ).all()
        policy_tables = {
            row.tablename for row in policies if row.qual is not None and row.with_check is not None
        }
        if policy_tables != set(TENANT_TABLES):
            raise RuntimeError("Not every tenant table has a complete RLS policy")

        for model in TENANT_MODELS:
            if db.scalar(select(model.org_id).limit(1)) is not None:
                raise RuntimeError(
                    f"PostgreSQL tenant RLS exposed {model.__tablename__} without context"
                )

        set_tenant_context(db, "org_acme")
        for model in TENANT_MODELS:
            org_ids = list(db.scalars(select(model.org_id).distinct()).all())
            if any(org_id != "org_acme" for org_id in org_ids):
                raise RuntimeError(
                    f"PostgreSQL tenant RLS leaked cross-context rows from {model.__tablename__}"
                )
        if db.scalar(select(Project.id).where(Project.id == "prj_beta_demo")) is not None:
            raise RuntimeError("PostgreSQL tenant RLS exposed a cross-organization project")

        _expect_rls_rejection(
            db,
            Project(
                id="prj_rls_rejected",
                org_id="org_beta",
                name="Rejected RLS write",
                domain="rejected-rls.example",
            ),
        )
        _expect_rls_rejection(
            db,
            AuditRateAttempt(id="rat_rls_rejected", org_id="org_beta"),
        )
        _expect_rls_rejection(
            db,
            Audit(
                id="aud_rls_rejected",
                org_id="org_beta",
                project_id="prj_beta_demo",
                idempotency_key="rejected-rls-write",
            ),
        )
        db.rollback()
    engine.dispose()


if __name__ == "__main__":
    verify()
