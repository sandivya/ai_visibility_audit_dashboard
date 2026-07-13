from datetime import timedelta

import pytest
from app.config import Settings
from app.database import SessionLocal
from app.models import (
    Audit,
    AuditPage,
    AuditStatus,
    SecurityAuditEvent,
    User,
    UserRole,
    UserSession,
    utcnow,
)
from app.provision_user import provision_user
from app.services import (
    record_worker_heartbeat,
    record_worker_poll,
    remove_worker_heartbeat,
    run_worker_once,
)
from app.worker_health import healthy
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError


def test_logout_revokes_opaque_server_session(client: TestClient) -> None:
    login = client.post("/api/auth/sessions", json={"user_id": "usr_alice"})
    assert login.status_code == 200
    token = client.cookies.get("visibility_session")
    assert token
    with SessionLocal() as db:
        session = db.scalar(select(UserSession))
        assert session is not None
        assert session.token_hash != token
        assert len(session.token_hash) == 64

    assert client.get("/api/projects").status_code == 200
    assert client.delete("/api/auth/sessions").status_code == 204
    assert client.get("/api/projects").status_code == 401
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(SecurityAuditEvent)) == 2


def test_expired_and_tampered_sessions_are_rejected(client: TestClient) -> None:
    assert client.post("/api/auth/sessions", json={"user_id": "usr_alice"}).status_code == 200
    with SessionLocal() as db:
        session = db.scalar(select(UserSession))
        assert session is not None
        session.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert client.get("/api/projects").status_code == 401
    client.cookies.set("visibility_session", "attacker-controlled")
    assert client.get("/api/projects").status_code == 401


def test_viewer_role_is_read_only(client: TestClient) -> None:
    with SessionLocal() as db:
        user = db.get(User, "usr_alice")
        assert user is not None
        user.role = UserRole.viewer
        db.commit()
    assert client.post("/api/auth/sessions", json={"user_id": "usr_alice"}).status_code == 200
    assert client.get("/api/projects").status_code == 200
    denied = client.post(
        "/api/projects",
        json={"name": "Forbidden", "domain": "forbidden.example"},
    )
    assert denied.status_code == 403


def test_oidc_provisioning_updates_role_and_disabling_revokes_sessions(
    client: TestClient,
) -> None:
    assert client.post("/api/auth/sessions", json={"user_id": "usr_alice"}).status_code == 200
    with SessionLocal() as db:
        user = provision_user(
            db,
            org_id="org_acme",
            org_name=None,
            email="ALICE@ACME.COM",
            role=UserRole.admin,
            issuer="https://identity.example.com/",
            subject="alice-subject",
            active=False,
        )
        assert user.email == "alice@acme.com"
        assert user.role == UserRole.admin
        assert user.oidc_issuer == "https://identity.example.com"
        assert db.scalar(select(UserSession.revoked_at)) is not None
    assert client.get("/api/projects").status_code == 401


def test_security_headers_and_unmatched_metric_are_bounded(
    client: TestClient, alice_headers: dict[str, str]
) -> None:
    response = client.get(
        "/api/projects",
        headers={**alice_headers, "X-Request-Id": "contains spaces and is rejected"},
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store, max-age=0"
    assert (
        response.headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"
    )
    assert response.headers["x-request-id"] != "contains spaces and is rejected"

    cors_response = client.get("/api/auth/config", headers={"Origin": "http://localhost:3000"})
    exposed_headers = {
        item.strip().lower()
        for item in cors_response.headers["access-control-expose-headers"].split(",")
    }
    assert {"retry-after", "x-request-id"} <= exposed_headers

    docs_response = client.get("/docs")
    assert docs_response.status_code == 200
    assert "https://cdn.jsdelivr.net" in docs_response.headers["content-security-policy"]

    client.get("/attacker-generated-unique-path")
    metrics = client.get("/metrics").text
    assert 'path="__unmatched__"' in metrics
    assert "attacker-generated-unique-path" not in metrics


def test_authenticated_cross_site_writes_are_rejected(
    client: TestClient, alice_headers: dict[str, str]
) -> None:
    response = client.post(
        "/api/projects",
        headers={
            **alice_headers,
            "Origin": "https://attacker.example",
            "Sec-Fetch-Site": "cross-site",
        },
        json={"name": "CSRF", "domain": "csrf.example"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_rejected"


def test_status_is_lightweight_and_evidence_is_scoped_and_paginated(
    client: TestClient, alice_headers: dict[str, str]
) -> None:
    created = client.post(
        "/api/projects/prj_acme_demo/audits",
        headers={**alice_headers, "Idempotency-Key": "bounded-evidence"},
    ).json()
    assert run_worker_once("enterprise-test-worker")
    with SessionLocal() as db:
        audit = db.get(Audit, created["id"])
        assert audit is not None
        for index in range(25):
            db.add(
                AuditPage(
                    org_id=audit.org_id,
                    audit_id=audit.id,
                    url=f"https://acmeskincare.com/evidence-{index}",
                    title=f"Evidence {index}",
                    status_code=200,
                )
            )
        db.commit()

    status_response = client.get(f"/api/audits/{created['id']}/status", headers=alice_headers)
    assert status_response.status_code == 200
    assert "pages" not in status_response.json()

    detail = client.get(
        f"/api/audits/{created['id']}?evidence_limit=5", headers=alice_headers
    ).json()
    assert detail["page_count"] == 27
    assert len(detail["pages"]) == 5
    assert detail["pages_next_cursor"]

    first = client.get(f"/api/audits/{created['id']}/pages?limit=10", headers=alice_headers).json()
    second = client.get(
        f"/api/audits/{created['id']}/pages?limit=10&cursor={first['next_cursor']}",
        headers=alice_headers,
    ).json()
    assert {item["id"] for item in first["items"]}.isdisjoint(
        {item["id"] for item in second["items"]}
    )
    assert (
        client.get(
            f"/api/audits/{created['id']}/prompts?cursor={first['next_cursor']}",
            headers=alice_headers,
        ).status_code
        == 400
    )


def test_database_rejects_inconsistent_terminal_audit() -> None:
    with SessionLocal() as db:
        db.add(
            Audit(
                org_id="org_acme",
                project_id="prj_acme_demo",
                idempotency_key="invalid-completed-payload",
                status=AuditStatus.completed,
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()


def test_worker_heartbeat_has_a_health_contract() -> None:
    record_worker_heartbeat("health-test-worker")
    assert not healthy()
    record_worker_poll("health-test-worker", worked=False)
    assert healthy()
    remove_worker_heartbeat("health-test-worker")
    assert not healthy()


def test_production_configuration_rejects_all_repository_defaults() -> None:
    common = {
        "app_env": "production",
        "database_url": "postgresql+psycopg://app:strong-password@db/visibility",
        "cors_origins": "https://dashboard.example.com",
        "frontend_url": "https://dashboard.example.com",
        "mock_auth_enabled": False,
        "secure_cookies": True,
        "session_cookie_name": "__Host-visibility_session",
        "oidc_server_metadata_url": "https://id.example.com/.well-known/openid-configuration",
        "oidc_client_id": "visibility",
        "oidc_client_secret": "provider-secret",
        "oidc_redirect_uri": "https://api.example.com/api/auth/oidc/callback",
        "expose_api_docs": False,
    }
    with pytest.raises(ValueError):
        Settings(session_secret="local-compose-session-secret-change-me", **common)
    with pytest.raises(ValueError):
        Settings(
            session_secret="a-production-signing-key-with-more-than-32-characters",
            database_url=("postgresql+psycopg://visibility_app:visibility-app-local@db/visibility"),
            **{key: value for key, value in common.items() if key != "database_url"},
        )
    valid = Settings(
        session_secret="a-production-signing-key-with-more-than-32-characters", **common
    )
    assert valid.oidc_enabled
