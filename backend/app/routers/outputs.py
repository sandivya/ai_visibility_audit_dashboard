from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import and_, or_, select

from app.auth import CurrentUser, Db, Writer
from app.config import get_settings
from app.database import set_tenant_context
from app.models import Audit, Finding, Project, Recommendation, utcnow
from app.pagination import cursor_scope, encode_cursor
from app.routers.common import cursor_values, finding_out, recommendation_out
from app.schemas import FindingPage, RecommendationOut, RecommendationUpdate

router = APIRouter()
settings = get_settings()


@router.get("/findings", response_model=FindingPage)
def list_findings(
    db: Db,
    user: CurrentUser,
    severity: Annotated[str | None, Query(max_length=20)] = None,
    category: Annotated[str | None, Query(max_length=60)] = None,
    audit_id: Annotated[str | None, Query(max_length=32)] = None,
    project_id: Annotated[str | None, Query(max_length=32)] = None,
    limit: Annotated[
        int, Query(ge=1, le=settings.cursor_max_page_size)
    ] = settings.cursor_page_size,
    cursor: str | None = None,
) -> FindingPage:
    scope = cursor_scope(
        "findings",
        org_id=user.org_id,
        severity=severity,
        category=category,
        audit_id=audit_id,
        project_id=project_id,
    )
    statement = (
        select(Finding, Audit.project_id, Project.name)
        .join(
            Audit,
            and_(Finding.org_id == Audit.org_id, Finding.audit_id == Audit.id),
        )
        .join(
            Project,
            and_(Audit.org_id == Project.org_id, Audit.project_id == Project.id),
        )
        .where(
            Finding.org_id == user.org_id,
            Audit.org_id == user.org_id,
            Project.org_id == user.org_id,
        )
    )
    if severity:
        statement = statement.where(Finding.severity == severity)
    if category:
        statement = statement.where(Finding.category == category)
    if audit_id:
        statement = statement.where(Finding.audit_id == audit_id)
    if project_id:
        statement = statement.where(Audit.project_id == project_id)
    values = cursor_values(cursor, scope)
    if values:
        created_at, row_id = values
        statement = statement.where(
            or_(
                Finding.created_at < created_at,
                and_(Finding.created_at == created_at, Finding.id < row_id),
            )
        )
    rows = list(
        db.execute(
            statement.order_by(Finding.created_at.desc(), Finding.id.desc()).limit(limit + 1)
        ).all()
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = (
        encode_cursor(rows[-1][0].created_at, rows[-1][0].id, scope) if has_more and rows else None
    )
    return FindingPage(
        items=[
            finding_out(finding, project_id=row_project_id, project_name=project_name)
            for finding, row_project_id, project_name in rows
        ],
        next_cursor=next_cursor,
    )


@router.patch("/recommendations/{recommendation_id}", response_model=RecommendationOut)
def update_recommendation(
    recommendation_id: str,
    payload: RecommendationUpdate,
    db: Db,
    user: Writer,
) -> RecommendationOut:
    recommendation = db.scalar(
        select(Recommendation).where(
            Recommendation.id == recommendation_id,
            Recommendation.org_id == user.org_id,
        )
    )
    if not recommendation:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    recommendation.status = payload.status
    recommendation.updated_at = utcnow()
    db.commit()
    set_tenant_context(db, user.org_id)
    db.refresh(recommendation)
    findings = db.scalars(
        select(Finding).where(
            Finding.org_id == user.org_id,
            Finding.audit_id == recommendation.audit_id,
        )
    ).all()
    return recommendation_out(
        recommendation,
        findings_by_title={finding.title: finding for finding in findings},
    )
