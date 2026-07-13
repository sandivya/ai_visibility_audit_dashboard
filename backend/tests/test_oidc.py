from collections.abc import Mapping
from typing import Any

import app.routers.auth_health as auth_health
import pytest
from app.config import get_settings
from app.database import SessionLocal
from app.models import SecurityAuditEvent, User, UserSession
from authlib.integrations.base_client.errors import OAuthError  # type: ignore[import-untyped]
from fastapi import Request, Response
from fastapi.testclient import TestClient
from sqlalchemy import func, select

ISSUER = "https://identity.example.com"


class FakeOIDCClient:
    server_metadata: dict[str, Any] = {"issuer": ISSUER}

    def __init__(
        self,
        claims: Mapping[str, object] | object | None = None,
        error: OAuthError | None = None,
    ) -> None:
        self.claims = claims
        self.error = error
        self.redirect_uri: str | None = None

    async def authorize_redirect(self, _request: Request, redirect_uri: str) -> Response:
        self.redirect_uri = redirect_uri
        return Response(status_code=204)

    async def authorize_access_token(self, _request: Request) -> dict[str, Any]:
        if self.error:
            raise self.error
        return {"userinfo": self.claims}


@pytest.fixture
def oidc_configuration() -> None:
    settings = get_settings()
    fields = (
        "oidc_server_metadata_url",
        "oidc_client_id",
        "oidc_client_secret",
        "oidc_redirect_uri",
        "oidc_auto_link_verified_email",
    )
    original = {field: getattr(settings, field) for field in fields}
    settings.oidc_server_metadata_url = f"{ISSUER}/.well-known/openid-configuration"
    settings.oidc_client_id = "visibility"
    settings.oidc_client_secret = "test-secret"
    settings.oidc_redirect_uri = "https://api.example.com/api/auth/oidc/callback"
    settings.oidc_auto_link_verified_email = False
    yield
    for field, value in original.items():
        setattr(settings, field, value)


def valid_claims(**overrides: object) -> dict[str, object]:
    claims: dict[str, object] = {
        "iss": ISSUER,
        "sub": "alice-identity",
        "email": "alice@acme.com",
        "email_verified": True,
    }
    claims.update(overrides)
    return claims


def test_oidc_login_uses_configured_canonical_redirect(
    client: TestClient,
    oidc_configuration: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeOIDCClient(valid_claims())
    monkeypatch.setattr(auth_health, "oidc_client", lambda: fake)
    response = client.get("/api/auth/oidc/login")
    assert response.status_code == 204
    assert fake.redirect_uri == "https://api.example.com/api/auth/oidc/callback"


def test_oidc_verified_email_auto_link_creates_server_session(
    client: TestClient,
    oidc_configuration: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    get_settings().oidc_auto_link_verified_email = True
    monkeypatch.setattr(auth_health, "oidc_client", lambda: FakeOIDCClient(valid_claims()))

    response = client.get("/api/auth/oidc/callback", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "http://localhost:3000/"
    assert "HttpOnly" in response.headers["set-cookie"]
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "alice@acme.com"

    with SessionLocal() as db:
        user = db.get(User, "usr_alice")
        assert user is not None
        assert (user.oidc_issuer, user.oidc_subject) == (ISSUER, "alice-identity")
        session = db.scalar(select(UserSession))
        assert session is not None
        assert session.auth_method == "oidc"


def test_oidc_preprovisioned_identity_succeeds_without_email_linking(
    client: TestClient,
    oidc_configuration: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with SessionLocal() as db:
        user = db.get(User, "usr_alice")
        assert user is not None
        user.oidc_issuer = ISSUER
        user.oidc_subject = "preprovisioned"
        db.commit()
    monkeypatch.setattr(
        auth_health,
        "oidc_client",
        lambda: FakeOIDCClient(valid_claims(sub="preprovisioned")),
    )
    assert client.get("/api/auth/oidc/callback", follow_redirects=False).status_code == 303


@pytest.mark.parametrize(
    "claims",
    (
        None,
        "not-a-claim-object",
        valid_claims(iss="https://attacker.example"),
        valid_claims(sub=""),
        valid_claims(sub="x" * 256),
        valid_claims(email="invalid-email"),
        valid_claims(email="alice @acme.com"),
        valid_claims(email_verified="true"),
    ),
)
def test_oidc_rejects_malformed_or_unverified_identity_claims(
    client: TestClient,
    oidc_configuration: None,
    monkeypatch: pytest.MonkeyPatch,
    claims: object,
) -> None:
    monkeypatch.setattr(auth_health, "oidc_client", lambda: FakeOIDCClient(claims))
    response = client.get("/api/auth/oidc/callback")
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Identity provider claims were not accepted"
    with SessionLocal() as db:
        event = db.scalar(select(SecurityAuditEvent))
        assert event is not None
        assert event.details["reason"] == "invalid_identity_claims"


def test_oidc_provider_failure_is_audited_without_leaking_details(
    client: TestClient,
    oidc_configuration: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_error = OAuthError(error="access_denied", description="sensitive provider text")
    monkeypatch.setattr(
        auth_health,
        "oidc_client",
        lambda: FakeOIDCClient(error=provider_error),
    )
    response = client.get("/api/auth/oidc/callback")
    assert response.status_code == 401
    assert "sensitive" not in response.text
    with SessionLocal() as db:
        event = db.scalar(select(SecurityAuditEvent))
        assert event is not None
        assert event.details == {"reason": "provider_rejected", "error": "access_denied"}


def test_oidc_rejects_unprovisioned_and_inactive_users(
    client: TestClient,
    oidc_configuration: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        auth_health,
        "oidc_client",
        lambda: FakeOIDCClient(valid_claims(email="unknown@example.com")),
    )
    assert client.get("/api/auth/oidc/callback").status_code == 403

    with SessionLocal() as db:
        user = db.get(User, "usr_alice")
        assert user is not None
        user.oidc_issuer = ISSUER
        user.oidc_subject = "alice-identity"
        user.is_active = False
        db.commit()
    monkeypatch.setattr(auth_health, "oidc_client", lambda: FakeOIDCClient(valid_claims()))
    assert client.get("/api/auth/oidc/callback").status_code == 403
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(UserSession)) == 0
