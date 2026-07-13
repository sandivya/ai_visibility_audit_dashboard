from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.auth import Db
from app.models import Audit, Finding
from app.pagination import InvalidCursor, decode_cursor
from app.schemas import FindingOut


def cursor_values(cursor: str | None, scope: str) -> tuple[datetime, str] | None:
    if not cursor:
        return None
    try:
        return decode_cursor(cursor, scope)
    except InvalidCursor as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def get_owned_audit(
    db: Db,
    org_id: str,
    audit_id: str,
    *,
    include_project: bool = False,
) -> Audit:
    statement = select(Audit).where(Audit.id == audit_id, Audit.org_id == org_id)
    if include_project:
        statement = statement.options(selectinload(Audit.project))
    audit = db.scalar(statement)
    if not audit:
        raise HTTPException(status_code=404, detail="Audit not found")
    return audit


def finding_out(finding: Finding, *, project_id: str, project_name: str) -> FindingOut:
    return FindingOut(
        id=finding.id,
        audit_id=finding.audit_id,
        project_id=project_id,
        project_name=project_name,
        severity=finding.severity,
        category=finding.category,
        title=finding.title,
        description=finding.description,
        created_at=finding.created_at,
    )
