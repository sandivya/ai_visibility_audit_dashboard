from datetime import timedelta

import pytest
from app.auth import cleanup_expired_sessions
from app.config import Settings, get_settings
from app.database import SessionLocal
from app.models import UserSession, WorkerHeartbeat, utcnow
from app.pagination import cursor_scope
from app.schema_health import SchemaNotReady, verify_database_readiness
from app.services import (
    latest_queue_observation,
    record_worker_heartbeat,
    record_worker_poll,
    record_worker_poll_failure,
    retry_delay_seconds,
)
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session


@pytest.mark.parametrize(
    ("overrides", "message"),
    (
        (
            {"session_touch_interval_seconds": 60, "session_idle_timeout_seconds": 60},
            "touch",
        ),
        (
            {"session_idle_timeout_seconds": 300, "session_ttl_seconds": 300},
            "idle",
        ),
        ({"session_same_site": "none", "secure_cookies": False}, "secure"),
        ({"session_retention_seconds": 300}, "retention"),
        ({"cursor_page_size": 101, "cursor_max_page_size": 100}, "cursor"),
        (
            {"audit_evidence_page_size": 101, "audit_evidence_max_page_size": 100},
            "evidence",
        ),
        (
            {"audit_retry_delay_seconds": 10, "audit_retry_max_delay_seconds": 5},
            "retry",
        ),
        ({"audit_step_delay_seconds": 2, "audit_lease_seconds": 2}, "lease"),
        (
            {"worker_poll_interval_seconds": 2, "worker_max_backoff_seconds": 1},
            "backoff",
        ),
        (
            {"worker_heartbeat_interval_seconds": 10, "worker_health_timeout_seconds": 15},
            "heartbeat",
        ),
        (
            {"database_lock_timeout_ms": 30_000},
            "lock",
        ),
        (
            {"database_statement_timeout_ms": 60_000},
            "statement",
        ),
    ),
)
def test_operational_configuration_invariants(overrides: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError) as error:
        Settings(**overrides)
    assert message in str(error.value).lower()


def production_settings(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "app_env": "production",
        "database_url": "postgresql+psycopg://app:strong-password@db/visibility",
        "cors_origins": "https://dashboard.example.com",
        "frontend_url": "https://dashboard.example.com",
        "allowed_hosts": "api.example.com",
        "mock_auth_enabled": False,
        "secure_cookies": True,
        "session_secret": "a-production-signing-key-with-more-than-32-characters",
        "session_cookie_name": "__Host-visibility_session",
        "oidc_server_metadata_url": "https://id.example.com/.well-known/openid-configuration",
        "oidc_client_id": "visibility",
        "oidc_client_secret": "provider-secret",
        "oidc_redirect_uri": "https://api.example.com/api/auth/oidc/callback",
        "expose_api_docs": False,
    }
    values.update(overrides)
    return values


@pytest.mark.parametrize(
    ("overrides", "message"),
    (
        ({"database_url": "sqlite:///production.db"}, "postgresql+psycopg"),
        (
            {"database_url": "postgresql+asyncpg://app:password@db/visibility"},
            "postgresql+psycopg",
        ),
        (
            {"database_url": "postgresql+psycopg://app@db/visibility"},
            "password",
        ),
        ({"cors_origins": "https://dashboard.example.com/path"}, "cors"),
        ({"frontend_url": "https://dashboard.example.com/?next=bad"}, "frontend"),
        ({"oidc_server_metadata_url": "http://id.example.com/metadata"}, "metadata"),
        (
            {"oidc_redirect_uri": "https://api.example.com/callback?next=bad"},
            "redirect",
        ),
        ({"oidc_scopes": "profile email"}, "openid"),
        ({"allowed_hosts": "*"}, "allowed_hosts"),
        ({"metrics_bearer_token": "too-short"}, "metrics"),
    ),
)
def test_production_rejects_unsafe_database_and_canonical_urls(
    overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError) as error:
        Settings(**production_settings(**overrides))
    assert message in str(error.value).lower()


def test_project_search_versioned_alias_and_openapi_error_contract(
    client: TestClient, alice_headers: dict[str, str]
) -> None:
    created = client.post(
        "/api/projects",
        headers=alice_headers,
        json={"name": "Searchable Aurora", "domain": "aurora-search.example"},
    )
    assert created.status_code == 201
    by_name = client.get("/api/projects?search=aurora", headers=alice_headers).json()
    by_domain = client.get("/api/projects?search=search.example", headers=alice_headers).json()
    assert [item["id"] for item in by_name["items"]] == [created.json()["id"]]
    assert [item["id"] for item in by_domain["items"]] == [created.json()["id"]]
    assert client.get("/api/projects?search=%20%20", headers=alice_headers).status_code == 422

    versioned = client.get("/api/v1/projects?search=aurora", headers=alice_headers)
    assert versioned.status_code == 200
    assert versioned.json()["items"][0]["id"] == created.json()["id"]

    schema = client.get("/openapi.json").json()
    assert "ErrorResponse" in schema["components"]["schemas"]
    unauthorized = schema["paths"]["/api/projects"]["get"]["responses"]["401"]
    assert unauthorized["content"]["application/json"]["schema"]["$ref"].endswith("/ErrorResponse")


def test_cursor_scopes_are_canonical_and_filter_bound() -> None:
    first = cursor_scope("findings", category="a:b", severity="c")
    second = cursor_scope("findings", category="a", severity="b:c")
    reordered = cursor_scope("findings", severity="c", category="a:b")
    assert first != second
    assert first == reordered
    assert len(first) < 100


def test_readiness_checks_schema_and_rejects_missing_tables(client: TestClient) -> None:
    assert client.get("/api/health/ready").json() == {"status": "ready"}

    isolated_engine = create_engine("sqlite:///:memory:")
    with Session(isolated_engine) as db:
        with pytest.raises(SchemaNotReady, match="tables"):
            verify_database_readiness(db, Settings(app_env="test"))
    isolated_engine.dispose()


def test_metrics_production_auth_and_worker_queue_observations(client: TestClient) -> None:
    settings = get_settings()
    original = (settings.app_env, settings.metrics_enabled, settings.metrics_bearer_token)
    token = "metrics-token-with-at-least-thirty-two-characters"
    try:
        settings.app_env = "production"
        settings.metrics_enabled = True
        settings.metrics_bearer_token = None
        assert client.get("/metrics").status_code == 404

        settings.metrics_bearer_token = token
        denied = client.get("/metrics", headers={"Authorization": "Bearer incorrect"})
        assert denied.status_code == 401
        assert denied.headers["www-authenticate"] == "Bearer"

        record_worker_heartbeat("metrics-worker")
        record_worker_poll("metrics-worker", worked=True)
        observation = latest_queue_observation()
        assert observation is not None
        assert observation.healthy_workers == 1
        metrics = client.get("/metrics", headers={"Authorization": f"Bearer {token}"})
        assert metrics.status_code == 200
        assert "visibility_audit_queue_depth" in metrics.text
        assert 'state="queued"' in metrics.text

        settings.metrics_enabled = False
        assert (
            client.get("/metrics", headers={"Authorization": f"Bearer {token}"}).status_code == 404
        )
    finally:
        settings.app_env, settings.metrics_enabled, settings.metrics_bearer_token = original


def test_retry_jitter_is_stable_exponential_and_bounded() -> None:
    settings = get_settings()
    original = (
        settings.audit_retry_delay_seconds,
        settings.audit_retry_max_delay_seconds,
        settings.audit_retry_jitter_ratio,
        settings.audit_max_attempts,
    )
    try:
        settings.audit_retry_delay_seconds = 2
        settings.audit_retry_max_delay_seconds = 10
        settings.audit_retry_jitter_ratio = 0.2
        settings.audit_max_attempts = 6
        delays = [retry_delay_seconds("aud_stable", attempt) for attempt in range(1, 7)]
        assert delays == [retry_delay_seconds("aud_stable", attempt) for attempt in range(1, 7)]
        assert delays == sorted(delays)
        assert 1.6 <= delays[0] <= 2.4
        assert all(0 < delay <= 10 for delay in delays)
    finally:
        (
            settings.audit_retry_delay_seconds,
            settings.audit_retry_max_delay_seconds,
            settings.audit_retry_jitter_ratio,
            settings.audit_max_attempts,
        ) = original


def test_session_cleanup_is_retention_aware_and_bounded() -> None:
    now = utcnow()
    with SessionLocal() as db:
        for index in range(2):
            db.add(
                UserSession(
                    org_id="org_acme",
                    user_id="usr_alice",
                    token_hash=f"{index:064x}",
                    auth_method="test",
                    expires_at=now - timedelta(days=30),
                )
            )
        db.add(
            UserSession(
                org_id="org_acme",
                user_id="usr_alice",
                token_hash="f" * 64,
                auth_method="test",
                expires_at=now - timedelta(minutes=1),
            )
        )
        db.commit()
        assert cleanup_expired_sessions(db, now=now, retention_seconds=86_400, batch_size=1) == 1
        assert cleanup_expired_sessions(db, now=now, retention_seconds=86_400, batch_size=10) == 1
        db.commit()
        remaining = list(db.scalars(select(UserSession)).all())
        assert len(remaining) == 1
        assert remaining[0].token_hash == "f" * 64


def test_worker_poll_failures_do_not_masquerade_as_success() -> None:
    record_worker_heartbeat("failure-worker")
    record_worker_poll_failure("failure-worker")
    with SessionLocal() as db:
        heartbeat = db.get(WorkerHeartbeat, "failure-worker")
        assert heartbeat is not None
        assert heartbeat.last_poll_at is None
        assert heartbeat.last_error_at is not None
        assert heartbeat.consecutive_failures == 1
