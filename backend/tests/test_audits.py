from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import app.services as services
import pytest
from app.config import get_settings
from app.database import SessionLocal
from app.models import Audit, AuditEvent, AuditEventType, AuditStatus, Project, utcnow
from app.services import (
    RateLimitExceeded,
    claim_next_audit,
    create_audit,
    run_worker_once,
    transition,
)
from fastapi.testclient import TestClient
from sqlalchemy import select


def start_and_process(
    client: TestClient,
    project_id: str,
    headers: dict[str, str],
    key: str,
) -> dict[str, object]:
    response = client.post(
        f"/api/projects/{project_id}/audits",
        headers={**headers, "Idempotency-Key": key},
    )
    assert response.status_code == 202
    assert run_worker_once("test-worker")
    return client.get(f"/api/audits/{response.json()['id']}", headers=headers).json()


def test_audit_completes_with_evidence(client: TestClient, alice_headers: dict[str, str]) -> None:
    detail = start_and_process(client, "prj_acme_demo", alice_headers, "complete-once")
    assert detail["status"] == "completed"
    assert detail["visibility_score"] == 68
    assert len(detail["pages"]) == len(detail["prompts"]) == 2
    assert len(detail["findings"]) == len(detail["recommendations"]) == 2
    assert detail["events"][0]["event_type"] == "audit_created"
    assert detail["events"][-1]["event_type"] == "audit_completed"
    assert sum(event["event_type"] == "page_analyzed" for event in detail["events"]) == 2


def test_idempotency_returns_original_audit(
    client: TestClient, alice_headers: dict[str, str]
) -> None:
    headers = {**alice_headers, "Idempotency-Key": "same-key"}
    first = client.post("/api/projects/prj_acme_demo/audits", headers=headers)
    second = client.post("/api/projects/prj_acme_demo/audits", headers=headers)
    assert first.json()["id"] == second.json()["id"]
    assert (
        len(client.get("/api/projects/prj_acme_demo/audits", headers=alice_headers).json()["items"])
        == 1
    )


def test_idempotency_key_is_scoped_to_organization_and_project(
    client: TestClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
) -> None:
    second_acme_project = client.post(
        "/api/projects",
        headers=alice_headers,
        json={"name": "Acme Labs", "domain": "labs.acmeskincare.com"},
    )
    assert second_acme_project.status_code == 201

    key = "shared-scope-key"
    targets = (
        ("prj_acme_demo", alice_headers),
        (second_acme_project.json()["id"], alice_headers),
        ("prj_beta_demo", bob_headers),
    )
    created_ids: list[str] = []
    for project_id, headers in targets:
        request_headers = {**headers, "Idempotency-Key": key}
        first = client.post(f"/api/projects/{project_id}/audits", headers=request_headers)
        replay = client.post(f"/api/projects/{project_id}/audits", headers=request_headers)
        assert first.status_code == replay.status_code == 202
        assert replay.json()["id"] == first.json()["id"]
        created_ids.append(first.json()["id"])

    assert len(set(created_ids)) == len(targets)
    with SessionLocal() as db:
        audits = list(db.scalars(select(Audit).where(Audit.idempotency_key == key)).all())
        assert {(audit.org_id, audit.project_id) for audit in audits} == {
            ("org_acme", "prj_acme_demo"),
            ("org_acme", second_acme_project.json()["id"]),
            ("org_beta", "prj_beta_demo"),
        }


def test_concurrent_idempotency_returns_one_audit() -> None:
    def create() -> tuple[str, bool]:
        with SessionLocal() as db:
            project = db.scalar(select(Project).where(Project.id == "prj_acme_demo"))
            assert project is not None
            audit, created = create_audit(db, project, "concurrent-key")
            return audit.id, created

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _index: create(), range(8)))
    assert len({audit_id for audit_id, _created in results}) == 1
    assert sum(created for _audit_id, created in results) == 1


def test_concurrent_rate_limit_is_atomic() -> None:
    settings = get_settings()
    original_limit = settings.audit_rate_limit
    settings.audit_rate_limit = 3

    def create(index: int) -> str:
        with SessionLocal() as db:
            project = db.scalar(select(Project).where(Project.id == "prj_acme_demo"))
            assert project is not None
            try:
                create_audit(db, project, f"rate-key-{index}")
                return "created"
            except RateLimitExceeded:
                db.rollback()
                return "limited"

    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(create, range(8)))
        assert results.count("created") == 3
        assert results.count("limited") == 5
    finally:
        settings.audit_rate_limit = original_limit


def test_cross_org_audit_is_hidden(
    client: TestClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
) -> None:
    created = client.post(
        "/api/projects/prj_beta_demo/audits",
        headers={**bob_headers, "Idempotency-Key": "beta"},
    ).json()
    assert client.get(f"/api/audits/{created['id']}", headers=alice_headers).status_code == 404
    assert (
        client.post(
            "/api/projects/prj_beta_demo/audits",
            headers={**alice_headers, "Idempotency-Key": "attack"},
        ).status_code
        == 404
    )


def test_cross_org_nested_audit_resources_are_hidden(
    client: TestClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
) -> None:
    created = client.post(
        "/api/projects/prj_beta_demo/audits",
        headers={**bob_headers, "Idempotency-Key": "nested-beta-evidence"},
    )
    assert created.status_code == 202
    assert run_worker_once("beta-evidence-worker")

    for resource in ("pages", "prompts", "findings", "recommendations", "events"):
        response = client.get(
            f"/api/audits/{created.json()['id']}/{resource}",
            headers=alice_headers,
        )
        assert response.status_code == 404, resource
        assert response.json()["error"]["message"] == "Audit not found", resource


def test_failed_domain_is_persisted(client: TestClient, alice_headers: dict[str, str]) -> None:
    project = client.post(
        "/api/projects",
        headers=alice_headers,
        json={"name": "Failure profile", "domain": "please-fail.com"},
    ).json()
    detail = start_and_process(client, project["id"], alice_headers, "fail")
    assert detail["status"] == "failed"
    assert detail["error_message"]
    assert detail["events"][-1]["event_type"] == "audit_failed"


def test_recommendation_status_and_finding_filters(
    client: TestClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
) -> None:
    detail = start_and_process(client, "prj_acme_demo", alice_headers, "outputs")
    recommendation_id = detail["recommendations"][0]["id"]
    updated = client.patch(
        f"/api/recommendations/{recommendation_id}",
        headers=alice_headers,
        json={"status": "in_progress"},
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "in_progress"
    assert (
        client.patch(
            f"/api/recommendations/{recommendation_id}",
            headers=bob_headers,
            json={"status": "completed"},
        ).status_code
        == 404
    )
    filtered = client.get(
        f"/api/findings?severity=high&category=ai_visibility&audit_id={detail['id']}&project_id=prj_acme_demo",
        headers=alice_headers,
    ).json()
    assert len(filtered["items"]) == 1
    assert filtered["items"][0]["severity"] == "high"
    assert (
        client.get("/api/findings?project_id=prj_acme_demo", headers=bob_headers).json()["items"]
        == []
    )


def test_state_machine_rejects_terminal_transition() -> None:
    audit = Audit(
        org_id="org",
        project_id="project",
        idempotency_key="key",
        status=AuditStatus.completed,
    )
    try:
        transition(audit, AuditStatus.processing)
        raise AssertionError("transition should have failed")
    except ValueError as exc:
        assert "completed -> processing" in str(exc)


def test_worker_retries_then_persists_terminal_failure(
    client: TestClient,
    alice_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    original_attempts = settings.audit_max_attempts
    original_delay = settings.audit_retry_delay_seconds
    settings.audit_max_attempts = 2
    settings.audit_retry_delay_seconds = 0

    created = client.post(
        "/api/projects/prj_acme_demo/audits",
        headers={**alice_headers, "Idempotency-Key": "retry-exhaustion"},
    ).json()

    def provider_outage(_audit_id: str, _worker_id: str) -> None:
        raise ConnectionError("provider unavailable")

    monkeypatch.setattr(services, "process_claimed_audit", provider_outage)
    try:
        assert run_worker_once("retry-worker")
        first = client.get(f"/api/audits/{created['id']}", headers=alice_headers).json()
        assert first["status"] == "processing"
        assert first["error_message"] == "Audit processing error: ConnectionError"
        assert first["events"][-1]["event_type"] == "audit_retry_scheduled"

        assert run_worker_once("retry-worker")
        final = client.get(f"/api/audits/{created['id']}", headers=alice_headers).json()
        assert final["status"] == "failed"
        assert final["events"][-1]["event_type"] == "audit_failed"
    finally:
        settings.audit_max_attempts = original_attempts
        settings.audit_retry_delay_seconds = original_delay


def test_stale_processing_lease_is_reclaimed_after_worker_restart(
    client: TestClient,
    alice_headers: dict[str, str],
) -> None:
    created = client.post(
        "/api/projects/prj_acme_demo/audits",
        headers={**alice_headers, "Idempotency-Key": "stale-worker-lease"},
    )
    assert created.status_code == 202
    audit_id = created.json()["id"]

    assert claim_next_audit("crashed-worker") == audit_id
    settings = get_settings()
    with SessionLocal() as db:
        audit = db.get(Audit, audit_id)
        assert audit is not None
        assert audit.status == AuditStatus.processing
        assert audit.worker_id == "crashed-worker"
        assert audit.attempt_count == 1
        audit.locked_at = utcnow() - timedelta(seconds=settings.audit_lease_seconds + 1)
        db.commit()

    assert run_worker_once("replacement-worker")

    with SessionLocal() as db:
        audit = db.get(Audit, audit_id)
        assert audit is not None
        assert audit.status == AuditStatus.completed
        assert audit.attempt_count == 2
        assert audit.worker_id is None
        assert audit.locked_at is None
        event_types = list(
            db.scalars(
                select(AuditEvent.event_type)
                .where(AuditEvent.audit_id == audit_id)
                .order_by(AuditEvent.created_at, AuditEvent.id)
            ).all()
        )
        assert event_types.count(AuditEventType.audit_retried) == 1
        assert event_types[-1] == AuditEventType.audit_completed
