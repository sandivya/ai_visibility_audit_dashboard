import hashlib
import logging
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import ceil

from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.database import SessionLocal, set_tenant_context
from app.models import (
    Audit,
    AuditEvent,
    AuditEventType,
    AuditPage,
    AuditPrompt,
    AuditRateAttempt,
    AuditStatus,
    Finding,
    Project,
    Recommendation,
    WorkerHeartbeat,
    utcnow,
)

logger = logging.getLogger(__name__)

VALID_TRANSITIONS = {
    AuditStatus.queued: {AuditStatus.processing},
    AuditStatus.processing: {AuditStatus.completed, AuditStatus.failed},
    AuditStatus.completed: set(),
    AuditStatus.failed: set(),
}


class RateLimitExceeded(Exception):
    def __init__(self, retry_after: int) -> None:
        self.retry_after = max(1, retry_after)
        super().__init__("Audit rate limit exceeded. Try again shortly.")


@dataclass(frozen=True)
class QueueObservation:
    observed_at: datetime
    queued_count: int
    processing_count: int
    retry_wait_count: int
    healthy_workers: int


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _database_now(db: Session) -> datetime:
    if db.get_bind().dialect.name != "postgresql":
        return utcnow()
    value = db.scalar(select(func.now()))
    return _aware(value) if isinstance(value, datetime) else utcnow()


def retry_delay_seconds(audit_id: str, attempt_count: int) -> float:
    """Return stable exponential jitter so retries remain bounded and testable."""
    settings = get_settings()
    exponent = max(0, min(attempt_count - 1, settings.audit_max_attempts - 1))
    unjittered = settings.audit_retry_delay_seconds * (2**exponent)
    digest = hashlib.sha256(f"{audit_id}:{attempt_count}".encode()).digest()
    unit_interval = int.from_bytes(digest[:8], "big") / ((1 << 64) - 1)
    jitter = settings.audit_retry_jitter_ratio
    factor = (1 - jitter) + (2 * jitter * unit_interval)
    return float(min(settings.audit_retry_max_delay_seconds, unjittered * factor))


def transition(audit: Audit, target: AuditStatus) -> None:
    if target not in VALID_TRANSITIONS[audit.status]:
        raise ValueError(f"Invalid audit transition: {audit.status.value} -> {target.value}")
    audit.status = target
    audit.updated_at = utcnow()


def event(db: Session, audit: Audit, event_type: AuditEventType, message: str) -> None:
    db.add(
        AuditEvent(
            org_id=audit.org_id,
            audit_id=audit.id,
            event_type=event_type,
            message=message,
        )
    )


_lock_guard = threading.Lock()
_organization_locks: dict[str, threading.Lock] = {}


def _local_organization_lock(org_id: str) -> threading.Lock:
    with _lock_guard:
        return _organization_locks.setdefault(org_id, threading.Lock())


@contextmanager
def organization_creation_lock(db: Session, org_id: str) -> Iterator[None]:
    if db.get_bind().dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:org_id, 0))"),
            {"org_id": org_id},
        )
        yield
        return
    lock = _local_organization_lock(org_id)
    with lock:
        yield


def enforce_rate_limit(db: Session, org_id: str) -> None:
    settings = get_settings()
    now = _database_now(db)
    cutoff = now - timedelta(seconds=settings.audit_rate_window_seconds)
    cleanup_cutoff = cutoff - timedelta(seconds=settings.audit_rate_window_seconds)
    db.execute(
        delete(AuditRateAttempt).where(
            AuditRateAttempt.org_id == org_id,
            AuditRateAttempt.created_at < cleanup_cutoff,
        )
    )
    attempts = db.scalar(
        select(func.count())
        .select_from(AuditRateAttempt)
        .where(
            AuditRateAttempt.org_id == org_id,
            AuditRateAttempt.created_at >= cutoff,
        )
    )
    if (attempts or 0) < settings.audit_rate_limit:
        return
    oldest = db.scalar(
        select(func.min(AuditRateAttempt.created_at)).where(
            AuditRateAttempt.org_id == org_id,
            AuditRateAttempt.created_at >= cutoff,
        )
    )
    retry_after = settings.audit_rate_window_seconds
    if oldest:
        if oldest.tzinfo is None:
            oldest = oldest.replace(tzinfo=UTC)
        retry_after = ceil(
            max(
                1.0,
                (
                    oldest + timedelta(seconds=settings.audit_rate_window_seconds) - now
                ).total_seconds(),
            )
        )
    raise RateLimitExceeded(retry_after)


def _existing_audit(db: Session, project: Project, key: str) -> Audit | None:
    return db.scalar(
        select(Audit).where(
            Audit.org_id == project.org_id,
            Audit.project_id == project.id,
            Audit.idempotency_key == key,
        )
    )


def create_audit(db: Session, project: Project, key: str) -> tuple[Audit, bool]:
    set_tenant_context(db, project.org_id)
    with organization_creation_lock(db, project.org_id):
        existing = _existing_audit(db, project, key)
        if existing:
            db.commit()
            return existing, False
        enforce_rate_limit(db, project.org_id)
        audit = Audit(org_id=project.org_id, project_id=project.id, idempotency_key=key)
        try:
            db.add(audit)
            db.flush()
            db.add(AuditRateAttempt(org_id=project.org_id))
            event(db, audit, AuditEventType.audit_created, "Audit queued for durable processing")
            db.flush()
            db.commit()
        except IntegrityError:
            db.rollback()
            set_tenant_context(db, project.org_id)
            existing = _existing_audit(db, project, key)
            if existing:
                return existing, False
            raise
        set_tenant_context(db, project.org_id)
        db.refresh(audit)
        return audit, True


def claim_next_audit(worker_id: str) -> str | None:
    settings = get_settings()
    with SessionLocal() as db:
        now = _database_now(db)
        stale_before = now - timedelta(seconds=settings.audit_lease_seconds)
        exhausted = list(
            db.scalars(
                select(Audit)
                .where(
                    Audit.status == AuditStatus.processing,
                    Audit.attempt_count >= settings.audit_max_attempts,
                    or_(Audit.locked_at.is_(None), Audit.locked_at < stale_before),
                )
                .with_for_update(skip_locked=True)
                .limit(20)
            ).all()
        )
        for stale_audit in exhausted:
            stale_audit.locked_at = None
            stale_audit.worker_id = None
            stale_audit.error_message = "Audit processing exhausted its retry budget."
            transition(stale_audit, AuditStatus.failed)
            event(
                db,
                stale_audit,
                AuditEventType.audit_failed,
                "Audit exhausted its retry budget after a stale worker lease",
            )
        audit = db.scalar(
            select(Audit)
            .where(
                Audit.attempt_count < settings.audit_max_attempts,
                Audit.available_at <= now,
                or_(
                    Audit.status == AuditStatus.queued,
                    (
                        (Audit.status == AuditStatus.processing)
                        & or_(Audit.locked_at.is_(None), Audit.locked_at < stale_before)
                    ),
                ),
            )
            .order_by(Audit.available_at, Audit.created_at, Audit.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not audit:
            if exhausted:
                db.commit()
            return None
        if audit.status == AuditStatus.queued:
            transition(audit, AuditStatus.processing)
            event(db, audit, AuditEventType.audit_started, "Visibility analysis started")
        else:
            event(db, audit, AuditEventType.audit_retried, "A stale audit lease was reclaimed")
        audit.attempt_count += 1
        audit.locked_at = now
        audit.worker_id = worker_id
        db.commit()
        return audit.id


def _load_claimed_audit(db: Session, audit_id: str, worker_id: str) -> Audit | None:
    return db.scalar(
        select(Audit)
        .options(selectinload(Audit.project))
        .where(
            Audit.id == audit_id,
            Audit.status == AuditStatus.processing,
            Audit.worker_id == worker_id,
        )
        .with_for_update()
    )


def process_claimed_audit(audit_id: str, worker_id: str) -> None:
    settings = get_settings()
    time.sleep(settings.audit_step_delay_seconds)
    with SessionLocal() as db:
        audit = _load_claimed_audit(db, audit_id, worker_id)
        if not audit:
            return
        if "fail" in audit.project.domain:
            transition(audit, AuditStatus.failed)
            audit.error_message = "The simulated provider could not analyze this domain."
            audit.locked_at = None
            audit.worker_id = None
            event(db, audit, AuditEventType.audit_failed, "Audit failed in the simulated provider")
            db.commit()
            return

        domain = audit.project.domain
        brand = audit.project.name
        competitors = audit.project.competitors
        page_rows = [
            AuditPage(
                org_id=audit.org_id,
                audit_id=audit.id,
                url=f"https://{domain}/",
                title=f"{brand} - Official site",
                status_code=200,
            ),
            AuditPage(
                org_id=audit.org_id,
                audit_id=audit.id,
                url=f"https://{domain}/products",
                title="Products",
                status_code=200,
            ),
        ]
        prompt_rows = [
            AuditPrompt(
                org_id=audit.org_id,
                audit_id=audit.id,
                prompt=f"best {brand.lower()} alternatives",
                mentioned_brand=False,
                competitors_mentioned=competitors[:1],
                source="simulated_ai_search",
            ),
            AuditPrompt(
                org_id=audit.org_id,
                audit_id=audit.id,
                prompt=f"is {brand.lower()} a trusted brand",
                mentioned_brand=True,
                competitors_mentioned=competitors[1:2],
                source="simulated_ai_search",
            ),
        ]
        finding_rows = [
            Finding(
                org_id=audit.org_id,
                audit_id=audit.id,
                severity="high",
                category="ai_visibility",
                title="Brand missing from a high-intent prompt",
                description=f"{brand} was absent while a competitor was mentioned.",
            ),
            Finding(
                org_id=audit.org_id,
                audit_id=audit.id,
                severity="medium",
                category="technical_seo",
                title="Product page title lacks context",
                description="The product page title does not communicate audience or differentiation.",
            ),
        ]
        recommendation_rows = [
            Recommendation(
                org_id=audit.org_id,
                audit_id=audit.id,
                priority="high",
                title="Publish comparison-led content",
                description="Target high-intent category prompts with clear claims, FAQs, and third-party evidence.",
            ),
            Recommendation(
                org_id=audit.org_id,
                audit_id=audit.id,
                priority="medium",
                title="Improve product metadata",
                description="Add category, audience, and differentiators to product page metadata.",
            ),
        ]
        db.add_all(page_rows)
        db.add_all(prompt_rows)
        db.add_all(finding_rows)
        db.add_all(recommendation_rows)
        for page in page_rows:
            event(db, audit, AuditEventType.page_analyzed, f"Analyzed {page.url}")
        for prompt in prompt_rows:
            event(db, audit, AuditEventType.prompt_checked, f"Checked prompt: {prompt.prompt}")
        for finding in finding_rows:
            event(db, audit, AuditEventType.finding_created, f"Finding created: {finding.title}")
        for recommendation in recommendation_rows:
            event(
                db,
                audit,
                AuditEventType.recommendation_created,
                f"Recommendation created: {recommendation.title}",
            )
        audit.visibility_score = 68 if competitors else 74
        audit.error_message = None
        audit.locked_at = None
        audit.worker_id = None
        transition(audit, AuditStatus.completed)
        event(
            db,
            audit,
            AuditEventType.audit_completed,
            f"Audit completed with score {audit.visibility_score}",
        )
        db.commit()


def handle_processing_error(audit_id: str, worker_id: str, exc: Exception) -> None:
    settings = get_settings()
    with SessionLocal() as db:
        audit = db.scalar(select(Audit).where(Audit.id == audit_id).with_for_update())
        if not audit or audit.worker_id != worker_id or audit.status != AuditStatus.processing:
            return
        safe_message = f"Audit processing error: {type(exc).__name__}"
        audit.error_message = safe_message
        audit.locked_at = None
        audit.worker_id = None
        if audit.attempt_count >= settings.audit_max_attempts:
            transition(audit, AuditStatus.failed)
            event(db, audit, AuditEventType.audit_failed, "Audit exhausted its retry budget")
        else:
            delay = retry_delay_seconds(audit.id, audit.attempt_count)
            now = _database_now(db)
            audit.available_at = now + timedelta(seconds=delay)
            audit.updated_at = now
            event(
                db,
                audit,
                AuditEventType.audit_retry_scheduled,
                f"Audit retry scheduled in {delay:.2f} seconds",
            )
        db.commit()


def run_worker_once(worker_id: str) -> bool:
    audit_id = claim_next_audit(worker_id)
    if not audit_id:
        return False
    logger.info(
        "audit_claimed",
        extra={"audit_id": audit_id, "worker_id": worker_id},
    )
    try:
        process_claimed_audit(audit_id, worker_id)
        logger.info(
            "audit_processing_finished",
            extra={"audit_id": audit_id, "worker_id": worker_id},
        )
    except Exception as exc:
        logger.exception(
            "audit_processing_failed",
            extra={"audit_id": audit_id, "worker_id": worker_id},
        )
        handle_processing_error(audit_id, worker_id, exc)
    return True


def record_worker_heartbeat(worker_id: str) -> None:
    with SessionLocal() as db:
        heartbeat = db.get(WorkerHeartbeat, worker_id)
        if heartbeat is None:
            db.add(WorkerHeartbeat(worker_id=worker_id))
        else:
            heartbeat.last_seen_at = _database_now(db)
        db.commit()


def record_worker_poll(worker_id: str, worked: bool) -> None:
    """Record a successful queue poll separately from process liveness."""
    with SessionLocal() as db:
        now = _database_now(db)
        heartbeat = db.get(WorkerHeartbeat, worker_id)
        if heartbeat is None:
            heartbeat = WorkerHeartbeat(worker_id=worker_id, last_seen_at=now)
            db.add(heartbeat)
        queued_count = int(
            db.scalar(
                select(func.count()).select_from(Audit).where(Audit.status == AuditStatus.queued)
            )
            or 0
        )
        processing_count = int(
            db.scalar(
                select(func.count())
                .select_from(Audit)
                .where(Audit.status == AuditStatus.processing)
            )
            or 0
        )
        retry_wait_count = int(
            db.scalar(
                select(func.count())
                .select_from(Audit)
                .where(
                    Audit.status == AuditStatus.processing,
                    Audit.worker_id.is_(None),
                    Audit.available_at > now,
                )
            )
            or 0
        )
        heartbeat.last_poll_at = now
        heartbeat.last_seen_at = now
        heartbeat.consecutive_failures = 0
        heartbeat.queued_count = queued_count
        heartbeat.processing_count = processing_count
        heartbeat.retry_wait_count = retry_wait_count
        if worked:
            heartbeat.last_progress_at = now
        db.commit()


def record_worker_poll_failure(worker_id: str) -> None:
    with SessionLocal() as db:
        now = _database_now(db)
        heartbeat = db.get(WorkerHeartbeat, worker_id)
        if heartbeat is None:
            heartbeat = WorkerHeartbeat(worker_id=worker_id, last_seen_at=now)
            db.add(heartbeat)
        heartbeat.last_error_at = now
        heartbeat.consecutive_failures += 1
        db.commit()


def latest_queue_observation() -> QueueObservation | None:
    settings = get_settings()
    with SessionLocal() as db:
        latest = db.scalar(
            select(WorkerHeartbeat)
            .where(WorkerHeartbeat.last_poll_at.is_not(None))
            .order_by(WorkerHeartbeat.last_poll_at.desc())
            .limit(1)
        )
        if latest is None or latest.last_poll_at is None:
            return None
        cutoff = _database_now(db) - timedelta(seconds=settings.worker_health_timeout_seconds)
        healthy_workers = int(
            db.scalar(
                select(func.count())
                .select_from(WorkerHeartbeat)
                .where(
                    WorkerHeartbeat.last_seen_at >= cutoff,
                    WorkerHeartbeat.last_poll_at >= cutoff,
                )
            )
            or 0
        )
        return QueueObservation(
            observed_at=_aware(latest.last_poll_at),
            queued_count=latest.queued_count,
            processing_count=latest.processing_count,
            retry_wait_count=latest.retry_wait_count,
            healthy_workers=healthy_workers,
        )


def remove_worker_heartbeat(worker_id: str) -> None:
    with SessionLocal() as db:
        heartbeat = db.get(WorkerHeartbeat, worker_id)
        if heartbeat is not None:
            db.delete(heartbeat)
            db.commit()
