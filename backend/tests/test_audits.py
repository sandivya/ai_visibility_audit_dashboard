from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import app.services as services
import pytest
from app.config import get_settings
from app.database import SessionLocal
from app.models import (
    Audit,
    AuditEvent,
    AuditEventType,
    AuditRateAttempt,
    AuditStatus,
    Project,
    RecommendationStatus,
    utcnow,
)
from app.services import (
    RateLimitExceeded,
    build_simulated_evidence,
    calculate_visibility_score,
    claim_next_audit,
    create_audit,
    process_claimed_audit,
    refresh_completed_simulated_audit,
    run_worker_once,
    transition,
)
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import selectinload


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
    assert 0 <= detail["visibility_score"] <= 100
    assert len(detail["pages"]) == len(detail["prompts"]) == 2
    assert len(detail["findings"]) == len(detail["recommendations"]) == 2
    assert detail["events"][0]["event_type"] == "audit_created"
    assert detail["events"][-1]["event_type"] == "audit_completed"
    assert sum(event["event_type"] == "page_analyzed" for event in detail["events"]) == 2
    assert detail["methodology"]["mode"] == "simulated"
    assert detail["methodology"]["version"] == "simulated-v2"
    assert "no live AI provider" in detail["methodology"]["disclosure"]
    findings_by_id = {finding["id"]: finding for finding in detail["findings"]}
    for recommendation in detail["recommendations"]:
        related = findings_by_id[recommendation["related_finding_id"]]
        assert recommendation["evidence_kind"] == related["evidence_kind"]
        assert recommendation["related_finding_category"] == related["category"]


def test_audit_lifecycle_status_summaries_and_output_endpoints(
    client: TestClient, alice_headers: dict[str, str]
) -> None:
    created = client.post(
        "/api/projects/prj_acme_demo/audits",
        headers={**alice_headers, "Idempotency-Key": "complete-contract"},
    )
    assert created.status_code == 202
    audit_id = created.json()["id"]

    queued = client.get(f"/api/audits/{audit_id}/status", headers=alice_headers)
    assert queued.status_code == 200
    assert queued.json()["status"] == "queued"
    assert queued.headers["Retry-After"] == "2"

    assert claim_next_audit("contract-worker") == audit_id
    processing = client.get(f"/api/audits/{audit_id}/status", headers=alice_headers)
    assert processing.json()["status"] == "processing"
    assert processing.headers["Retry-After"] == "2"

    process_claimed_audit(audit_id, "contract-worker")
    completed = client.get(f"/api/audits/{audit_id}/status", headers=alice_headers)
    assert completed.json()["status"] == "completed"
    assert "Retry-After" not in completed.headers

    detail = client.get(f"/api/audits/{audit_id}", headers=alice_headers).json()
    expected_counts = {
        "pages": detail["page_count"],
        "prompts": detail["prompt_count"],
        "findings": detail["finding_count"],
        "recommendations": detail["recommendation_count"],
        "events": detail["event_count"],
    }
    for resource, expected_count in expected_counts.items():
        response = client.get(f"/api/audits/{audit_id}/{resource}", headers=alice_headers)
        assert response.status_code == 200, resource
        assert len(response.json()["items"]) == expected_count, resource

    project = client.get("/api/projects/prj_acme_demo", headers=alice_headers).json()
    assert project["latest_audit"]["id"] == audit_id
    assert project["latest_audit"]["status"] == "completed"
    listed_project = next(
        item
        for item in client.get("/api/projects", headers=alice_headers).json()["items"]
        if item["id"] == "prj_acme_demo"
    )
    assert listed_project["latest_audit"] == project["latest_audit"]

    audits = client.get("/api/projects/prj_acme_demo/audits", headers=alice_headers).json()["items"]
    assert audits[0]["id"] == audit_id


def test_visibility_score_is_derived_from_evidence() -> None:
    healthy_pages = [
        services.AuditPage(
            url="https://example.com", title="Example official website", status_code=200
        )
    ]
    visible_prompts = [
        services.AuditPrompt(
            prompt="best example tools",
            mentioned_brand=True,
            competitors_mentioned=[],
            source="test",
        )
    ]
    hidden_prompts = [
        services.AuditPrompt(
            prompt="best example tools",
            mentioned_brand=False,
            competitors_mentioned=["competitor.com"],
            source="test",
        )
    ]

    assert calculate_visibility_score(healthy_pages, visible_prompts) == 100
    assert calculate_visibility_score(healthy_pages, hidden_prompts) == 45


def test_simulated_audits_are_stable_for_equivalent_project_configuration() -> None:
    project = Project(
        id="prj_score_variation",
        org_id="org_beta",
        name="Beta Finance",
        domain="betafinance.com",
        competitors=["finwise.com", "moneybeam.com"],
    )
    snapshots: list[tuple[object, ...]] = []

    for audit_id in (
        "aud_963f7ffc53cb44178a58",
        "aud_34987eb3b393449c9130",
        "aud_9900e1f18526448eb901",
    ):
        audit = Audit(
            id=audit_id,
            org_id=project.org_id,
            project_id=project.id,
            idempotency_key=audit_id,
            status=AuditStatus.processing,
            project=project,
        )
        pages, prompts, findings, recommendations = build_simulated_evidence(audit)
        snapshots.append(
            (
                tuple((page.url, page.title, page.status_code) for page in pages),
                tuple(
                    (
                        prompt.prompt,
                        prompt.mentioned_brand,
                        tuple(prompt.competitors_mentioned),
                        prompt.source,
                    )
                    for prompt in prompts
                ),
                tuple(
                    (finding.severity, finding.category, finding.title, finding.description)
                    for finding in findings
                ),
                tuple(
                    (recommendation.priority, recommendation.title, recommendation.description)
                    for recommendation in recommendations
                ),
                calculate_visibility_score(pages, prompts),
            )
        )
        assert len(pages) == len(prompts) == len(findings) == len(recommendations) == 2
        if pages[1].title == "Products":
            assert findings[1].category == "technical_seo"
            assert recommendations[1].title == "Improve product metadata"

    assert snapshots[0] == snapshots[1] == snapshots[2]

    reordered_project = Project(
        id="prj_score_reordered",
        org_id=project.org_id,
        name=project.name,
        domain=project.domain,
        competitors=list(reversed(project.competitors)),
    )
    reordered_audit = Audit(
        id="aud_reordered",
        org_id=project.org_id,
        project_id=reordered_project.id,
        idempotency_key="reordered",
        status=AuditStatus.processing,
        project=reordered_project,
    )
    reordered = build_simulated_evidence(reordered_audit)
    assert tuple((row.url, row.title, row.status_code) for row in reordered[0]) == snapshots[0][0]
    assert (
        tuple(
            (row.prompt, row.mentioned_brand, tuple(row.competitors_mentioned), row.source)
            for row in reordered[1]
        )
        == snapshots[0][1]
    )


def test_simulated_evidence_changes_when_relevant_inputs_change() -> None:
    baseline_project = Project(
        id="prj_baseline",
        org_id="org_acme",
        name="Acme",
        domain="acme.example.com",
        competitors=["rival.example.com"],
    )
    changed_project = Project(
        id="prj_changed",
        org_id="org_acme",
        name="Acme Plus",
        domain="acme-plus.example.com",
        competitors=["other.example.com"],
    )

    def evidence_for(project: Project, audit_id: str) -> tuple[object, ...]:
        audit = Audit(
            id=audit_id,
            org_id=project.org_id,
            project_id=project.id,
            idempotency_key=audit_id,
            status=AuditStatus.processing,
            project=project,
        )
        pages, prompts, findings, recommendations = build_simulated_evidence(audit)
        return pages[0].url, prompts[0].prompt, findings[1].title, recommendations[1].title

    assert evidence_for(baseline_project, "aud_baseline") != evidence_for(
        changed_project, "aud_changed"
    )


def test_simulated_audit_refresh_preserves_identity_status_and_timestamps(
    client: TestClient, bob_headers: dict[str, str]
) -> None:
    detail = start_and_process(client, "prj_beta_demo", bob_headers, "legacy-refresh")
    audit_id = str(detail["id"])

    with SessionLocal() as db:
        audit = db.scalar(
            select(Audit)
            .options(
                selectinload(Audit.project),
                selectinload(Audit.pages),
                selectinload(Audit.prompts),
                selectinload(Audit.findings),
                selectinload(Audit.recommendations),
                selectinload(Audit.events),
            )
            .where(Audit.id == audit_id)
        )
        assert audit is not None
        child_ids = {
            *(row.id for row in audit.pages),
            *(row.id for row in audit.prompts),
            *(row.id for row in audit.findings),
            *(row.id for row in audit.recommendations),
        }
        audit.recommendations[0].status = RecommendationStatus.in_progress
        score = refresh_completed_simulated_audit(audit)
        db.commit()

        completion = next(
            row for row in audit.events if row.event_type == AuditEventType.audit_completed
        )
        refreshed_child_ids = {
            *(row.id for row in audit.pages),
            *(row.id for row in audit.prompts),
            *(row.id for row in audit.findings),
            *(row.id for row in audit.recommendations),
        }
        assert refreshed_child_ids == child_ids
        assert audit.recommendations[0].status == RecommendationStatus.in_progress
        assert audit.updated_at == completion.created_at
        assert completion.message == f"Audit completed with score {score}"
        assert any(
            row.message == f"Finding created: {audit.findings[1].title}" for row in audit.events
        )


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


@pytest.mark.parametrize("key", (None, "   ", "x" * 129))
def test_audit_requires_a_bounded_idempotency_key(
    client: TestClient,
    alice_headers: dict[str, str],
    key: str | None,
) -> None:
    headers = dict(alice_headers)
    if key is not None:
        headers["Idempotency-Key"] = key

    response = client.post("/api/projects/prj_acme_demo/audits", headers=headers)

    assert response.status_code == 400
    assert "Idempotency-Key" in response.json()["error"]["message"]


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


def test_audit_creation_uses_one_database_timestamp(monkeypatch: pytest.MonkeyPatch) -> None:
    database_now = datetime(2026, 7, 16, 12, 30, tzinfo=UTC)
    calls = 0

    def fixed_database_now(_db: object) -> datetime:
        nonlocal calls
        calls += 1
        return database_now

    monkeypatch.setattr(services, "_database_now", fixed_database_now)
    with SessionLocal() as db:
        project = db.scalar(select(Project).where(Project.id == "prj_acme_demo"))
        assert project is not None
        audit, created = create_audit(db, project, "database-clock")
        attempt = db.scalar(
            select(AuditRateAttempt).where(AuditRateAttempt.org_id == project.org_id)
        )
        assert created
        assert attempt is not None

        def aware(value: datetime) -> datetime:
            return value if value.tzinfo else value.replace(tzinfo=UTC)

        assert calls == 1
        assert aware(audit.available_at) == database_now
        assert aware(audit.created_at) == database_now
        assert aware(audit.updated_at) == database_now
        assert aware(attempt.created_at) == database_now


def test_rate_limit_returns_consistent_error_and_retry_header(
    client: TestClient, alice_headers: dict[str, str]
) -> None:
    settings = get_settings()
    original_limit = settings.audit_rate_limit
    settings.audit_rate_limit = 1
    try:
        first = client.post(
            "/api/projects/prj_acme_demo/audits",
            headers={**alice_headers, "Idempotency-Key": "rate-contract-1"},
        )
        limited = client.post(
            "/api/projects/prj_acme_demo/audits",
            headers={**alice_headers, "Idempotency-Key": "rate-contract-2"},
        )

        assert first.status_code == 202
        assert limited.status_code == 429
        assert limited.json()["error"]["code"] == "http_429"
        assert "rate limit" in limited.json()["error"]["message"].lower()
        assert int(limited.headers["Retry-After"]) >= 1
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
    assert detail["retryable"] is False
    assert detail["failure_kind"] == "deterministic_demo"
    assert detail["events"][-1]["event_type"] == "audit_failed"
    status = client.get(f"/api/audits/{detail['id']}/status", headers=alice_headers).json()
    assert status["retryable"] is False
    assert status["failure_kind"] == "deterministic_demo"


def test_recommendation_status_and_finding_filters(
    client: TestClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
) -> None:
    detail = start_and_process(client, "prj_acme_demo", alice_headers, "outputs")
    recommendation_id = detail["recommendations"][0]["id"]
    for status in ("in_progress", "completed", "dismissed", "open"):
        updated = client.patch(
            f"/api/recommendations/{recommendation_id}",
            headers=alice_headers,
            json={"status": status},
        )
        assert updated.status_code == 200
        assert updated.json()["status"] == status
    invalid = client.patch(
        f"/api/recommendations/{recommendation_id}",
        headers=alice_headers,
        json={"status": "not-a-status"},
    )
    assert invalid.status_code == 422
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
        assert final["retryable"] is True
        assert final["failure_kind"] is None
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
