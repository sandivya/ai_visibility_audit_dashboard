import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, Request, status
from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.database import get_db, set_tenant_context
from app.models import SecurityAuditEvent, User, UserRole, UserSession, utcnow

Db = Annotated[Session, Depends(get_db)]
settings = get_settings()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _request_metadata(request: Request | None) -> tuple[str | None, str | None]:
    if request is None:
        return None, None
    ip_address = request.client.host[:45] if request.client else None
    user_agent = request.headers.get("User-Agent")
    return ip_address, user_agent[:512] if user_agent else None


def security_event(
    db: Session,
    *,
    action: str,
    outcome: str,
    request: Request | None = None,
    user: User | None = None,
    details: dict[str, object] | None = None,
) -> None:
    ip_address, user_agent = _request_metadata(request)
    db.add(
        SecurityAuditEvent(
            org_id=user.org_id if user else None,
            user_id=user.id if user else None,
            action=action,
            outcome=outcome,
            ip_address=ip_address,
            user_agent=user_agent,
            details=details or {},
        )
    )


def create_user_session(
    db: Session,
    user: User,
    *,
    auth_method: str,
    request: Request | None = None,
) -> str:
    now = utcnow()
    token = secrets.token_urlsafe(32)
    ip_address, user_agent = _request_metadata(request)
    db.add(
        UserSession(
            org_id=user.org_id,
            user_id=user.id,
            token_hash=_token_hash(token),
            auth_method=auth_method,
            ip_address=ip_address,
            user_agent=user_agent,
            expires_at=now + timedelta(seconds=settings.session_ttl_seconds),
        )
    )
    security_event(
        db,
        action="session_created",
        outcome="success",
        request=request,
        user=user,
        details={"auth_method": auth_method},
    )
    db.commit()
    return token


def cleanup_expired_sessions(
    db: Session,
    *,
    now: datetime | None = None,
    retention_seconds: int | None = None,
    batch_size: int | None = None,
) -> int:
    """Delete one bounded batch; callers can schedule and repeat this safely."""
    current_time = now or utcnow()
    retention = retention_seconds or settings.session_retention_seconds
    limit = batch_size or settings.session_cleanup_batch_size
    cutoff = current_time - timedelta(seconds=retention)
    candidate_statement = (
        select(UserSession.id)
        .where(
            or_(
                UserSession.expires_at < cutoff,
                UserSession.revoked_at < cutoff,
            )
        )
        .order_by(UserSession.expires_at, UserSession.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    candidate_ids = list(db.scalars(candidate_statement).all())
    if candidate_ids:
        db.execute(delete(UserSession).where(UserSession.id.in_(candidate_ids)))
    return len(candidate_ids)


def revoke_user_session(db: Session, token: str | None, request: Request | None = None) -> None:
    if not token:
        return
    session = db.scalar(
        select(UserSession)
        .options(selectinload(UserSession.user))
        .where(UserSession.token_hash == _token_hash(token))
    )
    if not session or session.revoked_at is not None:
        return
    session.revoked_at = utcnow()
    security_event(
        db,
        action="session_revoked",
        outcome="success",
        request=request,
        user=session.user,
    )
    db.commit()


def get_current_user(
    request: Request,
    db: Db,
    session_token: Annotated[str | None, Cookie(alias=settings.session_cookie_name)] = None,
) -> User:
    if not session_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )
    session = db.scalar(
        select(UserSession)
        .options(selectinload(UserSession.user).selectinload(User.organization))
        .where(UserSession.token_hash == _token_hash(session_token))
    )
    now = utcnow()
    if (
        not session
        or session.revoked_at is not None
        or _aware(session.expires_at) <= now
        or _aware(session.last_seen_at)
        < now - timedelta(seconds=settings.session_idle_timeout_seconds)
        or not session.user.is_active
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Session is invalid or expired"
        )

    if _aware(session.last_seen_at) < now - timedelta(
        seconds=settings.session_touch_interval_seconds
    ):
        session.last_seen_at = now
        db.commit()

    set_tenant_context(db, session.org_id)
    request.state.session_id = session.id
    request.state.user_id = session.user_id
    request.state.org_id = session.org_id
    return session.user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_write_access(user: CurrentUser) -> User:
    if user.role not in {UserRole.owner, UserRole.admin, UserRole.member}:
        raise HTTPException(status_code=403, detail="This role has read-only access")
    return user


Writer = Annotated[User, Depends(require_write_access)]
