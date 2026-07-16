from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.auth import Db
from app.methodology import (
    evidence_kind_for_finding,
    evidence_kind_for_recommendation,
    related_finding_title,
)
from app.models import Audit, Finding, Recommendation
from app.pagination import InvalidCursor, decode_cursor
from app.schemas import FindingOut, RecommendationOut


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
        evidence_kind=evidence_kind_for_finding(finding.category),
        title=finding.title,
        description=finding.description,
        created_at=finding.created_at,
    )


def recommendation_out(
    recommendation: Recommendation,
    *,
    findings_by_title: dict[str, Finding] | None = None,
) -> RecommendationOut:
    related_title = related_finding_title(recommendation.title)
    related_finding = (findings_by_title or {}).get(related_title or "")
    return RecommendationOut(
        id=recommendation.id,
        audit_id=recommendation.audit_id,
        priority=recommendation.priority,
        title=recommendation.title,
        description=recommendation.description,
        status=recommendation.status,
        evidence_kind=evidence_kind_for_recommendation(recommendation.title),
        related_finding_id=related_finding.id if related_finding else None,
        related_finding_category=related_finding.category if related_finding else None,
        created_at=recommendation.created_at,
        updated_at=recommendation.updated_at,
    )
