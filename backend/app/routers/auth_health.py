from collections.abc import Mapping
from typing import Annotated

from authlib.integrations.base_client.errors import OAuthError  # type: ignore[import-untyped]
from fastapi import APIRouter, Cookie, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.auth import (
    CurrentUser,
    Db,
    create_user_session,
    revoke_user_session,
    security_event,
)
from app.config import get_settings
from app.models import User
from app.oidc import oidc_client
from app.schema_health import SchemaNotReady, verify_database_readiness
from app.schemas import AuthConfigOut, SessionCreate, UserOut

router = APIRouter()
settings = get_settings()


def user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        org_id=user.org_id,
        organization_name=user.organization.name,
        role=user.role,
    )


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.secure_cookies,
        samesite=settings.session_same_site,
        path="/",
    )


@router.get("/health")
@router.get("/health/live")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
def readiness(db: Db) -> dict[str, str]:
    try:
        verify_database_readiness(db, settings)
    except SchemaNotReady as exc:
        raise HTTPException(status_code=503, detail="Service dependencies are not ready") from exc
    return {"status": "ready"}


@router.get("/auth/config", response_model=AuthConfigOut)
def auth_config() -> AuthConfigOut:
    return AuthConfigOut(
        mock_auth_enabled=settings.mock_auth_enabled,
        oidc_enabled=settings.oidc_enabled,
        oidc_login_url="/api/auth/oidc/login" if settings.oidc_enabled else None,
    )


@router.get("/auth/users", response_model=list[UserOut])
def login_users(db: Db) -> list[UserOut]:
    if not settings.mock_auth_enabled:
        raise HTTPException(status_code=404, detail="Not found")
    rows = db.scalars(
        select(User)
        .options(selectinload(User.organization))
        .where(User.is_active.is_(True))
        .order_by(User.email)
    ).all()
    return [user_out(user) for user in rows]


@router.post("/auth/sessions", response_model=UserOut)
def create_mock_session(
    payload: SessionCreate,
    request: Request,
    response: Response,
    db: Db,
) -> UserOut:
    if not settings.mock_auth_enabled:
        raise HTTPException(status_code=404, detail="Not found")
    user = db.scalar(
        select(User)
        .options(selectinload(User.organization))
        .where(User.id == payload.user_id, User.is_active.is_(True))
    )
    if not user:
        security_event(
            db,
            action="mock_login",
            outcome="failure",
            request=request,
            details={"reason": "unknown_user"},
        )
        db.commit()
        raise HTTPException(status_code=401, detail="Unknown user")
    token = create_user_session(db, user, auth_method="mock", request=request)
    set_session_cookie(response, token)
    return user_out(user)


@router.get("/auth/oidc/login")
async def oidc_login(request: Request) -> Response:
    if not settings.oidc_enabled:
        raise HTTPException(status_code=404, detail="Not found")
    redirect_uri = settings.oidc_redirect_uri or str(request.url_for("oidc_callback"))
    return await oidc_client().authorize_redirect(request, redirect_uri)


@router.get("/auth/oidc/callback", name="oidc_callback")
async def oidc_callback(request: Request, db: Db) -> Response:
    if not settings.oidc_enabled:
        raise HTTPException(status_code=404, detail="Not found")
    client = oidc_client()
    try:
        token = await client.authorize_access_token(request)
    except OAuthError as exc:
        security_event(
            db,
            action="oidc_login",
            outcome="failure",
            request=request,
            details={"reason": "provider_rejected", "error": exc.error or "oauth_error"},
        )
        db.commit()
        raise HTTPException(status_code=401, detail="Identity provider login failed") from exc

    raw_claims = token.get("userinfo")
    claims: Mapping[str, object] = raw_claims if isinstance(raw_claims, Mapping) else {}
    raw_issuer = claims.get("iss")
    raw_subject = claims.get("sub")
    raw_email = claims.get("email")
    issuer = raw_issuer.rstrip("/") if isinstance(raw_issuer, str) else ""
    subject = raw_subject.strip() if isinstance(raw_subject, str) else ""
    email = raw_email.lower().strip() if isinstance(raw_email, str) else ""
    expected_issuer = str(client.server_metadata.get("issuer") or "").rstrip("/")
    email_verified = claims.get("email_verified") is True
    valid_email = (
        3 <= len(email) <= 255
        and "@" in email
        and not any(character.isspace() or ord(character) < 32 for character in email)
    )
    if (
        not issuer
        or issuer != expected_issuer
        or not subject
        or len(subject) > 255
        or not valid_email
        or not email_verified
    ):
        security_event(
            db,
            action="oidc_login",
            outcome="failure",
            request=request,
            details={"reason": "invalid_identity_claims"},
        )
        db.commit()
        raise HTTPException(status_code=401, detail="Identity provider claims were not accepted")

    user = db.scalar(
        select(User)
        .options(selectinload(User.organization))
        .where(User.oidc_issuer == issuer, User.oidc_subject == subject)
    )
    if not user and settings.oidc_auto_link_verified_email:
        candidate = db.scalar(
            select(User)
            .options(selectinload(User.organization))
            .where(func.lower(User.email) == email)
        )
        if candidate and candidate.oidc_issuer is None and candidate.oidc_subject is None:
            candidate.oidc_issuer = issuer
            candidate.oidc_subject = subject
            db.commit()
            user = candidate

    if not user or not user.is_active:
        security_event(
            db,
            action="oidc_login",
            outcome="failure",
            request=request,
            user=user,
            details={"reason": "user_not_provisioned_or_inactive"},
        )
        db.commit()
        raise HTTPException(status_code=403, detail="This identity is not provisioned")

    session_token = create_user_session(db, user, auth_method="oidc", request=request)
    response = RedirectResponse(settings.frontend_url.rstrip("/") + "/", status_code=303)
    set_session_cookie(response, session_token)
    return response


@router.delete("/auth/sessions", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(
    request: Request,
    response: Response,
    db: Db,
    session_token: Annotated[str | None, Cookie(alias=settings.session_cookie_name)] = None,
) -> Response:
    revoke_user_session(db, session_token, request)
    response.delete_cookie(
        settings.session_cookie_name,
        path="/",
        secure=settings.secure_cookies,
        httponly=True,
        samesite=settings.session_same_site,
    )
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/auth/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    return user_out(user)
