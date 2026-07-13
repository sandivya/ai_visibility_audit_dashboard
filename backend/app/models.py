import uuid
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


def utcnow() -> datetime:
    return datetime.now(UTC)


class AuditStatus(StrEnum):
    queued = "queued"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class RecommendationStatus(StrEnum):
    open = "open"
    in_progress = "in_progress"
    completed = "completed"
    dismissed = "dismissed"


class UserRole(StrEnum):
    owner = "owner"
    admin = "admin"
    member = "member"
    viewer = "viewer"


class AuditEventType(StrEnum):
    audit_created = "audit_created"
    audit_started = "audit_started"
    audit_retried = "audit_retried"
    page_analyzed = "page_analyzed"
    prompt_checked = "prompt_checked"
    finding_created = "finding_created"
    recommendation_created = "recommendation_created"
    audit_retry_scheduled = "audit_retry_scheduled"
    audit_completed = "audit_completed"
    audit_failed = "audit_failed"


def enum_column(enum: type[StrEnum], name: str, length: int) -> Enum:
    return Enum(
        enum,
        name=name,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        length=length,
    )


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_users_org_id"),
        UniqueConstraint("oidc_issuer", "oidc_subject", name="uq_users_oidc_identity"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    org_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    role: Mapped[UserRole] = mapped_column(
        enum_column(UserRole, "user_role", 20),
        default=UserRole.member,
        server_default=UserRole.member.value,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    oidc_issuer: Mapped[str | None] = mapped_column(String(512))
    oidc_subject: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    organization: Mapped[Organization] = relationship()


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_projects_org_id"),
        Index("ix_projects_org_created_id", "org_id", "created_at", "id"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("prj"))
    org_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    domain: Mapped[str] = mapped_column(String(253))
    competitors: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        server_default=func.now(),
    )
    audits: Mapped[list["Audit"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", passive_deletes=True
    )


class Audit(Base):
    __tablename__ = "audits"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "project_id"],
            ["projects.org_id", "projects.id"],
            name="fk_audits_tenant_project",
            ondelete="CASCADE",
        ),
        UniqueConstraint("org_id", "id", name="uq_audits_org_id"),
        UniqueConstraint("org_id", "project_id", "idempotency_key", name="uq_audit_idempotency"),
        CheckConstraint(
            "visibility_score IS NULL OR (visibility_score >= 0 AND visibility_score <= 100)",
            name="ck_audits_visibility_score",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_audits_attempt_count"),
        CheckConstraint(
            "(status = 'queued' AND visibility_score IS NULL AND error_message IS NULL) OR "
            "(status = 'processing' AND visibility_score IS NULL) OR "
            "(status = 'completed' AND visibility_score IS NOT NULL AND error_message IS NULL) OR "
            "(status = 'failed' AND visibility_score IS NULL AND error_message IS NOT NULL)",
            name="ck_audits_status_payload",
        ),
        CheckConstraint(
            "(worker_id IS NULL AND locked_at IS NULL) OR "
            "(worker_id IS NOT NULL AND locked_at IS NOT NULL)",
            name="ck_audits_lease_pair",
        ),
        Index("ix_audits_org_project_created_id", "org_id", "project_id", "created_at", "id"),
        Index("ix_audits_worker_queue", "status", "available_at", "locked_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("aud"))
    org_id: Mapped[str] = mapped_column(String(32), index=True)
    project_id: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[AuditStatus] = mapped_column(
        enum_column(AuditStatus, "audit_status", 20), default=AuditStatus.queued
    )
    visibility_score: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    worker_id: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        server_default=func.now(),
    )
    project: Mapped[Project] = relationship(back_populates="audits")
    pages: Mapped[list["AuditPage"]] = relationship(
        back_populates="audit", cascade="all, delete-orphan", passive_deletes=True
    )
    prompts: Mapped[list["AuditPrompt"]] = relationship(
        back_populates="audit", cascade="all, delete-orphan", passive_deletes=True
    )
    findings: Mapped[list["Finding"]] = relationship(
        back_populates="audit", cascade="all, delete-orphan", passive_deletes=True
    )
    recommendations: Mapped[list["Recommendation"]] = relationship(
        back_populates="audit", cascade="all, delete-orphan", passive_deletes=True
    )
    events: Mapped[list["AuditEvent"]] = relationship(
        back_populates="audit", cascade="all, delete-orphan", passive_deletes=True
    )


class AuditPage(Base):
    __tablename__ = "audit_pages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "audit_id"],
            ["audits.org_id", "audits.id"],
            name="fk_audit_pages_tenant_audit",
            ondelete="CASCADE",
        ),
        Index("ix_audit_pages_org_audit_created", "org_id", "audit_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("pag"))
    org_id: Mapped[str] = mapped_column(String(32))
    audit_id: Mapped[str] = mapped_column(String(32), index=True)
    url: Mapped[str] = mapped_column(String(2048))
    title: Mapped[str] = mapped_column(String(255))
    status_code: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    audit: Mapped[Audit] = relationship(back_populates="pages")


class AuditPrompt(Base):
    __tablename__ = "audit_prompts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "audit_id"],
            ["audits.org_id", "audits.id"],
            name="fk_audit_prompts_tenant_audit",
            ondelete="CASCADE",
        ),
        Index("ix_audit_prompts_org_audit_created", "org_id", "audit_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("pro"))
    org_id: Mapped[str] = mapped_column(String(32))
    audit_id: Mapped[str] = mapped_column(String(32), index=True)
    prompt: Mapped[str] = mapped_column(Text)
    mentioned_brand: Mapped[bool] = mapped_column(Boolean)
    competitors_mentioned: Mapped[list[str]] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    audit: Mapped[Audit] = relationship(back_populates="prompts")


class Finding(Base):
    __tablename__ = "findings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "audit_id"],
            ["audits.org_id", "audits.id"],
            name="fk_findings_tenant_audit",
            ondelete="CASCADE",
        ),
        Index("ix_findings_org_audit_created", "org_id", "audit_id", "created_at"),
        Index("ix_findings_org_severity_category", "org_id", "severity", "category", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("fnd"))
    org_id: Mapped[str] = mapped_column(String(32))
    audit_id: Mapped[str] = mapped_column(String(32), index=True)
    severity: Mapped[str] = mapped_column(String(20))
    category: Mapped[str] = mapped_column(String(60))
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    audit: Mapped[Audit] = relationship(back_populates="findings")


class Recommendation(Base):
    __tablename__ = "recommendations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "audit_id"],
            ["audits.org_id", "audits.id"],
            name="fk_recommendations_tenant_audit",
            ondelete="CASCADE",
        ),
        Index("ix_recommendations_org_audit_created", "org_id", "audit_id", "created_at"),
        Index("ix_recommendations_org_status", "org_id", "status", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("rec"))
    org_id: Mapped[str] = mapped_column(String(32))
    audit_id: Mapped[str] = mapped_column(String(32), index=True)
    priority: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[RecommendationStatus] = mapped_column(
        enum_column(RecommendationStatus, "recommendation_status", 20),
        default=RecommendationStatus.open,
        server_default=RecommendationStatus.open.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        server_default=func.now(),
    )
    audit: Mapped[Audit] = relationship(back_populates="recommendations")


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "audit_id"],
            ["audits.org_id", "audits.id"],
            name="fk_audit_events_tenant_audit",
            ondelete="CASCADE",
        ),
        Index("ix_events_org_audit_created", "org_id", "audit_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("evt"))
    org_id: Mapped[str] = mapped_column(String(32))
    audit_id: Mapped[str] = mapped_column(String(32), index=True)
    event_type: Mapped[AuditEventType] = mapped_column(
        enum_column(AuditEventType, "audit_event_type", 40)
    )
    message: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    audit: Mapped[Audit] = relationship(back_populates="events")


class AuditRateAttempt(Base):
    __tablename__ = "audit_rate_attempts"
    __table_args__ = (Index("ix_rate_org_created", "org_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("rat"))
    org_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )


class UserSession(Base):
    __tablename__ = "user_sessions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "user_id"],
            ["users.org_id", "users.id"],
            name="fk_user_sessions_tenant_user",
            ondelete="CASCADE",
        ),
        Index("ix_user_sessions_user_active", "org_id", "user_id", "revoked_at", "expires_at"),
        Index("ix_user_sessions_expiry", "expires_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("ses"))
    org_id: Mapped[str] = mapped_column(String(32), index=True)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    auth_method: Mapped[str] = mapped_column(String(20))
    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user: Mapped[User] = relationship()


class SecurityAuditEvent(Base):
    __tablename__ = "security_audit_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "user_id"],
            ["users.org_id", "users.id"],
            name="fk_security_events_tenant_user",
            ondelete="SET NULL",
        ),
        Index("ix_security_events_org_created", "org_id", "created_at", "id"),
        Index("ix_security_events_action_created", "action", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("sec"))
    org_id: Mapped[str | None] = mapped_column(String(32))
    user_id: Mapped[str | None] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(80))
    outcome: Mapped[str] = mapped_column(String(20))
    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(512))
    details: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"
    __table_args__ = (
        CheckConstraint("consecutive_failures >= 0", name="ck_worker_failures_nonnegative"),
        CheckConstraint("queued_count >= 0", name="ck_worker_queued_nonnegative"),
        CheckConstraint("processing_count >= 0", name="ck_worker_processing_nonnegative"),
        CheckConstraint("retry_wait_count >= 0", name="ck_worker_retry_wait_nonnegative"),
    )

    worker_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), index=True
    )
    last_poll_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_progress_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    queued_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    processing_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    retry_wait_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
