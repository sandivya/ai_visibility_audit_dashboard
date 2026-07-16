from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import (
    Audit,
    AuditEvent,
    AuditEventType,
    AuditPage,
    AuditPrompt,
    AuditStatus,
    Finding,
    Organization,
    Project,
    Recommendation,
    RecommendationStatus,
    User,
    UserRole,
    utcnow,
)
from app.services import build_simulated_evidence, calculate_visibility_score

DEMO_AUDIT_IDEMPOTENCY_KEY = "seeded-completed-simulated-v2"
DEMO_AUDIT_IDS = {
    "prj_acme_demo": "aud_35a0c6e294ab4f6e9d12",
    "prj_beta_demo": "aud_b7e49dc231c84a05a6f3",
}


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _organization(db: Session, *, org_id: str, name: str, created_at: datetime) -> Organization:
    organization = db.get(Organization, org_id)
    if organization is None:
        organization = Organization(id=org_id, name=name, created_at=created_at)
        db.add(organization)
    else:
        organization.name = name
    return organization


def _user(
    db: Session,
    *,
    user_id: str,
    org_id: str,
    email: str,
    created_at: datetime,
) -> None:
    user = db.get(User, user_id)
    if user is None:
        db.add(
            User(
                id=user_id,
                org_id=org_id,
                email=email,
                role=UserRole.owner,
                created_at=created_at,
            )
        )
        return
    user.org_id = org_id
    user.email = email
    user.role = UserRole.owner
    user.is_active = True


def _project(
    db: Session,
    *,
    project_id: str,
    org_id: str,
    name: str,
    domain: str,
    competitors: list[str],
    created_at: datetime,
) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        project = Project(
            id=project_id,
            org_id=org_id,
            name=name,
            domain=domain,
            competitors=competitors,
            created_at=created_at,
            updated_at=created_at,
        )
        db.add(project)
    else:
        project.org_id = org_id
        project.name = name
        project.domain = domain
        project.competitors = competitors
    return project


def _event_messages(
    pages: list[AuditPage],
    prompts: list[AuditPrompt],
    findings: list[Finding],
    recommendations: list[Recommendation],
) -> list[tuple[AuditEventType, str]]:
    return [
        (AuditEventType.audit_created, "Demo audit queued for durable processing"),
        (AuditEventType.audit_started, "Visibility analysis started"),
        *[(AuditEventType.page_analyzed, f"Analyzed {page.url}") for page in pages],
        *[
            (AuditEventType.prompt_checked, f"Checked prompt: {prompt.prompt}")
            for prompt in prompts
        ],
        *[
            (AuditEventType.finding_created, f"Finding created: {finding.title}")
            for finding in findings
        ],
        *[
            (
                AuditEventType.recommendation_created,
                f"Recommendation created: {recommendation.title}",
            )
            for recommendation in recommendations
        ],
    ]


def _completed_demo_audit(db: Session, project: Project, *, now: datetime) -> None:
    existing = db.scalar(
        select(Audit).where(
            Audit.org_id == project.org_id,
            Audit.project_id == project.id,
            Audit.idempotency_key == DEMO_AUDIT_IDEMPOTENCY_KEY,
        )
    )
    if existing is not None:
        return

    completed_at = now
    started_at = max(_aware(project.created_at), completed_at - timedelta(minutes=8))
    duration = completed_at - started_at
    audit = Audit(
        id=DEMO_AUDIT_IDS[project.id],
        org_id=project.org_id,
        project_id=project.id,
        project=project,
        status=AuditStatus.completed,
        idempotency_key=DEMO_AUDIT_IDEMPOTENCY_KEY,
        attempt_count=1,
        available_at=started_at,
        created_at=started_at,
        updated_at=completed_at,
    )
    pages, prompts, findings, recommendations = build_simulated_evidence(audit)
    audit.visibility_score = calculate_visibility_score(pages, prompts)
    db.add(audit)
    db.flush()

    index = 2
    for page in pages:
        page.created_at = started_at + duration * (index / 12)
        index += 1
    for prompt in prompts:
        prompt.created_at = started_at + duration * (index / 12)
        index += 1
    for finding in findings:
        finding.created_at = started_at + duration * (index / 12)
        index += 1
    for recommendation in recommendations:
        recommendation.created_at = started_at + duration * (index / 12)
        recommendation.updated_at = recommendation.created_at
        index += 1
    recommendations[0].status = RecommendationStatus.in_progress
    db.add_all([*pages, *prompts, *findings, *recommendations])

    messages = _event_messages(pages, prompts, findings, recommendations)
    messages.append(
        (AuditEventType.audit_completed, f"Audit completed with score {audit.visibility_score}")
    )
    for index, (event_type, message) in enumerate(messages):
        db.add(
            AuditEvent(
                org_id=audit.org_id,
                audit_id=audit.id,
                event_type=event_type,
                message=message,
                created_at=started_at + duration * (index / max(1, len(messages) - 1)),
            )
        )


def seed(*, include_demo_audits: bool = True) -> None:
    with SessionLocal() as db:
        now = utcnow()
        demo_created_at = now - timedelta(days=1)
        acme = _organization(
            db, org_id="org_acme", name="Acme Skincare", created_at=demo_created_at
        )
        beta = _organization(db, org_id="org_beta", name="Beta Finance", created_at=demo_created_at)
        db.flush()
        _user(
            db,
            user_id="usr_alice",
            org_id=acme.id,
            email="alice@acme.com",
            created_at=demo_created_at,
        )
        _user(
            db,
            user_id="usr_bob",
            org_id=beta.id,
            email="bob@beta.com",
            created_at=demo_created_at,
        )
        acme_project = _project(
            db,
            project_id="prj_acme_demo",
            org_id=acme.id,
            name="Acme Skincare",
            domain="acmeskincare.com",
            competitors=["glowco.com", "naturalskin.com"],
            created_at=demo_created_at,
        )
        beta_project = _project(
            db,
            project_id="prj_beta_demo",
            org_id=beta.id,
            name="Beta Finance",
            domain="betafinance.com",
            competitors=["finwise.com", "moneybeam.com"],
            created_at=demo_created_at,
        )
        db.flush()
        if include_demo_audits:
            _completed_demo_audit(db, acme_project, now=now)
            _completed_demo_audit(db, beta_project, now=now)
        db.commit()


if __name__ == "__main__":
    seed()
