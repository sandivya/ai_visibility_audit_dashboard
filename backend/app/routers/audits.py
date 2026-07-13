from typing import Annotated, Any

from fastapi import APIRouter, Query, Response
from sqlalchemy import and_, func, or_, select

from app.auth import CurrentUser, Db
from app.config import get_settings
from app.models import Audit, AuditEvent, AuditPrompt, Finding, Recommendation
from app.models import AuditPage as AuditPageModel
from app.pagination import cursor_scope, encode_cursor
from app.routers.common import cursor_values, finding_out, get_owned_audit
from app.schemas import (
    AnalyzedPagePage,
    AuditOut,
    AuditPromptPage,
    AuditStatusOut,
    EventPage,
    FindingPage,
    RecommendationPage,
)

router = APIRouter()
settings = get_settings()


def _evidence_rows(
    db: Db,
    model: Any,
    *,
    org_id: str,
    audit_id: str,
    limit: int,
    cursor: str | None,
    scope: str,
) -> tuple[list[Any], str | None]:
    statement = select(model).where(model.org_id == org_id, model.audit_id == audit_id)
    values = cursor_values(cursor, scope)
    if values:
        created_at, row_id = values
        statement = statement.where(
            or_(
                model.created_at > created_at,
                and_(model.created_at == created_at, model.id > row_id),
            )
        )
    rows = list(db.scalars(statement.order_by(model.created_at, model.id).limit(limit + 1)).all())
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = (
        encode_cursor(rows[-1].created_at, rows[-1].id, scope) if has_more and rows else None
    )
    return rows, next_cursor


def _evidence_scope(org_id: str, audit_id: str, kind: str) -> str:
    return cursor_scope("audit-evidence", org_id=org_id, audit_id=audit_id, kind=kind)


def _evidence_counts(db: Db, org_id: str, audit_id: str) -> dict[str, int]:
    models = (
        ("pages", AuditPageModel),
        ("prompts", AuditPrompt),
        ("findings", Finding),
        ("recommendations", Recommendation),
        ("events", AuditEvent),
    )
    statement = select(
        *(
            select(func.count())
            .select_from(model)
            .where(model.org_id == org_id, model.audit_id == audit_id)
            .scalar_subquery()
            .label(kind)
            for kind, model in models
        )
    )
    row = db.execute(statement).one()
    return {kind: int(row[index] or 0) for index, (kind, _model) in enumerate(models)}


@router.get("/audits/{audit_id}", response_model=AuditOut)
def get_audit(
    audit_id: str,
    db: Db,
    user: CurrentUser,
    evidence_limit: Annotated[
        int, Query(ge=1, le=settings.audit_evidence_max_page_size)
    ] = settings.audit_evidence_page_size,
) -> AuditOut:
    audit = get_owned_audit(db, user.org_id, audit_id, include_project=True)
    collections: dict[str, tuple[list[Any], str | None]] = {}
    for kind, model in (
        ("pages", AuditPageModel),
        ("prompts", AuditPrompt),
        ("findings", Finding),
        ("recommendations", Recommendation),
        ("events", AuditEvent),
    ):
        collections[kind] = _evidence_rows(
            db,
            model,
            org_id=user.org_id,
            audit_id=audit.id,
            limit=evidence_limit,
            cursor=None,
            scope=_evidence_scope(user.org_id, audit.id, kind),
        )
    collections["findings"] = (
        [
            finding_out(
                finding,
                project_id=audit.project_id,
                project_name=audit.project.name,
            )
            for finding in collections["findings"][0]
        ],
        collections["findings"][1],
    )
    counts = _evidence_counts(db, user.org_id, audit.id)
    return AuditOut(
        id=audit.id,
        project_id=audit.project_id,
        status=audit.status,
        visibility_score=audit.visibility_score,
        error_message=audit.error_message,
        created_at=audit.created_at,
        updated_at=audit.updated_at,
        pages=collections["pages"][0],
        prompts=collections["prompts"][0],
        findings=collections["findings"][0],
        recommendations=collections["recommendations"][0],
        events=collections["events"][0],
        page_count=counts["pages"],
        prompt_count=counts["prompts"],
        finding_count=counts["findings"],
        recommendation_count=counts["recommendations"],
        event_count=counts["events"],
        pages_next_cursor=collections["pages"][1],
        prompts_next_cursor=collections["prompts"][1],
        findings_next_cursor=collections["findings"][1],
        recommendations_next_cursor=collections["recommendations"][1],
        events_next_cursor=collections["events"][1],
    )


@router.get("/audits/{audit_id}/status", response_model=AuditStatusOut)
def get_audit_status(audit_id: str, response: Response, db: Db, user: CurrentUser) -> Audit:
    audit = get_owned_audit(db, user.org_id, audit_id)
    if audit.status.value in {"queued", "processing"}:
        response.headers["Retry-After"] = "2"
    return audit


@router.get("/audits/{audit_id}/pages", response_model=AnalyzedPagePage)
def list_audit_pages(
    audit_id: str,
    db: Db,
    user: CurrentUser,
    limit: Annotated[
        int, Query(ge=1, le=settings.audit_evidence_max_page_size)
    ] = settings.audit_evidence_page_size,
    cursor: str | None = None,
) -> AnalyzedPagePage:
    get_owned_audit(db, user.org_id, audit_id)
    items, next_cursor = _evidence_rows(
        db,
        AuditPageModel,
        org_id=user.org_id,
        audit_id=audit_id,
        limit=limit,
        cursor=cursor,
        scope=_evidence_scope(user.org_id, audit_id, "pages"),
    )
    return AnalyzedPagePage(items=items, next_cursor=next_cursor)


@router.get("/audits/{audit_id}/prompts", response_model=AuditPromptPage)
def list_audit_prompts(
    audit_id: str,
    db: Db,
    user: CurrentUser,
    limit: Annotated[
        int, Query(ge=1, le=settings.audit_evidence_max_page_size)
    ] = settings.audit_evidence_page_size,
    cursor: str | None = None,
) -> AuditPromptPage:
    get_owned_audit(db, user.org_id, audit_id)
    items, next_cursor = _evidence_rows(
        db,
        AuditPrompt,
        org_id=user.org_id,
        audit_id=audit_id,
        limit=limit,
        cursor=cursor,
        scope=_evidence_scope(user.org_id, audit_id, "prompts"),
    )
    return AuditPromptPage(items=items, next_cursor=next_cursor)


@router.get("/audits/{audit_id}/findings", response_model=FindingPage)
def list_audit_findings(
    audit_id: str,
    db: Db,
    user: CurrentUser,
    limit: Annotated[
        int, Query(ge=1, le=settings.audit_evidence_max_page_size)
    ] = settings.audit_evidence_page_size,
    cursor: str | None = None,
) -> FindingPage:
    audit = get_owned_audit(db, user.org_id, audit_id, include_project=True)
    items, next_cursor = _evidence_rows(
        db,
        Finding,
        org_id=user.org_id,
        audit_id=audit_id,
        limit=limit,
        cursor=cursor,
        scope=_evidence_scope(user.org_id, audit_id, "findings"),
    )
    return FindingPage(
        items=[
            finding_out(
                finding,
                project_id=audit.project_id,
                project_name=audit.project.name,
            )
            for finding in items
        ],
        next_cursor=next_cursor,
    )


@router.get("/audits/{audit_id}/recommendations", response_model=RecommendationPage)
def list_audit_recommendations(
    audit_id: str,
    db: Db,
    user: CurrentUser,
    limit: Annotated[
        int, Query(ge=1, le=settings.audit_evidence_max_page_size)
    ] = settings.audit_evidence_page_size,
    cursor: str | None = None,
) -> RecommendationPage:
    get_owned_audit(db, user.org_id, audit_id)
    items, next_cursor = _evidence_rows(
        db,
        Recommendation,
        org_id=user.org_id,
        audit_id=audit_id,
        limit=limit,
        cursor=cursor,
        scope=_evidence_scope(user.org_id, audit_id, "recommendations"),
    )
    return RecommendationPage(items=items, next_cursor=next_cursor)


@router.get("/audits/{audit_id}/events", response_model=EventPage)
def list_audit_events(
    audit_id: str,
    db: Db,
    user: CurrentUser,
    limit: Annotated[
        int, Query(ge=1, le=settings.audit_evidence_max_page_size)
    ] = settings.audit_evidence_page_size,
    cursor: str | None = None,
) -> EventPage:
    get_owned_audit(db, user.org_id, audit_id)
    items, next_cursor = _evidence_rows(
        db,
        AuditEvent,
        org_id=user.org_id,
        audit_id=audit_id,
        limit=limit,
        cursor=cursor,
        scope=_evidence_scope(user.org_id, audit_id, "events"),
    )
    return EventPage(items=items, next_cursor=next_cursor)
