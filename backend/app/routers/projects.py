from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, status
from sqlalchemy import and_, func, or_, select

from app.auth import CurrentUser, Db, Writer
from app.config import get_settings
from app.database import set_tenant_context
from app.models import Audit, Project
from app.pagination import cursor_scope, encode_cursor
from app.routers.common import cursor_values
from app.schemas import (
    AuditPage,
    AuditSummary,
    ProjectCreate,
    ProjectOut,
    ProjectPage,
)
from app.services import RateLimitExceeded, create_audit

router = APIRouter()
settings = get_settings()


def _latest_audits(db: Db, org_id: str, project_ids: list[str]) -> dict[str, Audit]:
    if not project_ids:
        return {}
    ranked = (
        select(
            Audit.id.label("audit_id"),
            func.row_number()
            .over(
                partition_by=Audit.project_id,
                order_by=(Audit.created_at.desc(), Audit.id.desc()),
            )
            .label("row_number"),
        )
        .where(Audit.org_id == org_id, Audit.project_id.in_(project_ids))
        .subquery()
    )
    audits = db.scalars(
        select(Audit).join(ranked, ranked.c.audit_id == Audit.id).where(ranked.c.row_number == 1)
    ).all()
    return {audit.project_id: audit for audit in audits}


def project_out(project: Project, latest: Audit | None = None) -> ProjectOut:
    return ProjectOut(
        id=project.id,
        name=project.name,
        domain=project.domain,
        competitors=project.competitors,
        created_at=project.created_at,
        updated_at=project.updated_at,
        latest_audit=AuditSummary.model_validate(latest) if latest else None,
    )


def get_owned_project(db: Db, org_id: str, project_id: str) -> Project:
    project = db.scalar(select(Project).where(Project.id == project_id, Project.org_id == org_id))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.post("/projects", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, db: Db, user: Writer) -> ProjectOut:
    project = Project(org_id=user.org_id, **payload.model_dump())
    db.add(project)
    db.commit()
    set_tenant_context(db, user.org_id)
    db.refresh(project)
    return project_out(project)


@router.get("/projects", response_model=ProjectPage)
def list_projects(
    db: Db,
    user: CurrentUser,
    limit: Annotated[
        int, Query(ge=1, le=settings.cursor_max_page_size)
    ] = settings.cursor_page_size,
    cursor: str | None = None,
    search: Annotated[str | None, Query(min_length=1, max_length=120)] = None,
) -> ProjectPage:
    normalized_search = search.strip().casefold() if search else None
    if search and not normalized_search:
        raise HTTPException(status_code=422, detail="Search cannot be blank")
    scope = cursor_scope("projects", org_id=user.org_id, search=normalized_search)
    statement = select(Project).where(Project.org_id == user.org_id)
    if normalized_search:
        statement = statement.where(
            or_(
                Project.name.icontains(normalized_search, autoescape=True),
                Project.domain.icontains(normalized_search, autoescape=True),
            )
        )
    values = cursor_values(cursor, scope)
    if values:
        created_at, row_id = values
        statement = statement.where(
            or_(
                Project.created_at < created_at,
                and_(Project.created_at == created_at, Project.id < row_id),
            )
        )
    rows = list(
        db.scalars(
            statement.order_by(Project.created_at.desc(), Project.id.desc()).limit(limit + 1)
        ).all()
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    latest = _latest_audits(db, user.org_id, [project.id for project in rows])
    next_cursor = (
        encode_cursor(rows[-1].created_at, rows[-1].id, scope) if has_more and rows else None
    )
    return ProjectPage(
        items=[project_out(project, latest.get(project.id)) for project in rows],
        next_cursor=next_cursor,
    )


@router.get("/projects/{project_id}", response_model=ProjectOut)
def get_project(project_id: str, db: Db, user: CurrentUser) -> ProjectOut:
    project = get_owned_project(db, user.org_id, project_id)
    latest = _latest_audits(db, user.org_id, [project.id]).get(project.id)
    return project_out(project, latest)


@router.post("/projects/{project_id}/audits", response_model=AuditSummary, status_code=202)
def start_audit(
    project_id: str,
    db: Db,
    user: Writer,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Audit:
    if not idempotency_key or not idempotency_key.strip() or len(idempotency_key) > 128:
        raise HTTPException(status_code=400, detail="A valid Idempotency-Key header is required")
    project = get_owned_project(db, user.org_id, project_id)
    try:
        audit, _created = create_audit(db, project, idempotency_key.strip())
    except RateLimitExceeded as exc:
        raise HTTPException(
            status_code=429,
            detail=str(exc),
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc
    return audit


@router.get("/projects/{project_id}/audits", response_model=AuditPage)
def list_audits(
    project_id: str,
    db: Db,
    user: CurrentUser,
    limit: Annotated[
        int, Query(ge=1, le=settings.cursor_max_page_size)
    ] = settings.cursor_page_size,
    cursor: str | None = None,
) -> AuditPage:
    get_owned_project(db, user.org_id, project_id)
    scope = cursor_scope("audits", org_id=user.org_id, project_id=project_id)
    statement = select(Audit).where(
        Audit.project_id == project_id,
        Audit.org_id == user.org_id,
    )
    values = cursor_values(cursor, scope)
    if values:
        created_at, row_id = values
        statement = statement.where(
            or_(
                Audit.created_at < created_at,
                and_(Audit.created_at == created_at, Audit.id < row_id),
            )
        )
    rows = list(
        db.scalars(
            statement.order_by(Audit.created_at.desc(), Audit.id.desc()).limit(limit + 1)
        ).all()
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = (
        encode_cursor(rows[-1].created_at, rows[-1].id, scope) if has_more and rows else None
    )
    return AuditPage(
        items=[AuditSummary.model_validate(audit) for audit in rows],
        next_cursor=next_cursor,
    )
