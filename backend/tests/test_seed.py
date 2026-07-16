from app.database import SessionLocal
from app.models import Audit, AuditEventType, AuditStatus, RecommendationStatus
from app.seed import (
    ACME_FAILED_PROJECT_ID,
    ACME_UNAUDITED_PROJECT_ID,
    DEMO_AUDIT_IDEMPOTENCY_KEY,
    DEMO_AUDIT_IDS,
    seed,
)
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload


def test_demo_seed_provides_complete_audit_for_each_workspace(
    client: TestClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
) -> None:
    seed()

    for headers, project_id in (
        (alice_headers, "prj_acme_demo"),
        (bob_headers, "prj_beta_demo"),
    ):
        project = client.get(f"/api/projects/{project_id}", headers=headers).json()
        summary = project["latest_audit"]
        assert summary["status"] == "completed"
        assert 0 < summary["visibility_score"] <= 100

        detail = client.get(f"/api/audits/{summary['id']}", headers=headers).json()
        assert detail["status"] == "completed"
        assert len(detail["pages"]) == 2
        assert len(detail["prompts"]) == 2
        assert len(detail["findings"]) == 2
        assert len(detail["recommendations"]) == 2
        assert detail["recommendations"][0]["status"] in {"open", "in_progress"}
        assert detail["events"][0]["event_type"] == "audit_created"
        assert detail["events"][-1]["event_type"] == "audit_completed"

    acme_projects = client.get("/api/projects", headers=alice_headers).json()["items"]
    assert [project["id"] for project in acme_projects] == [
        "prj_acme_demo",
        ACME_FAILED_PROJECT_ID,
        ACME_UNAUDITED_PROJECT_ID,
    ]
    assert [
        project["latest_audit"]["status"] if project["latest_audit"] else None
        for project in acme_projects
    ] == ["completed", "failed", None]

    failed = client.get(f"/api/projects/{ACME_FAILED_PROJECT_ID}", headers=alice_headers).json()
    failed_detail = client.get(
        f"/api/audits/{failed['latest_audit']['id']}", headers=alice_headers
    ).json()
    assert failed_detail["status"] == "failed"
    assert failed_detail["failure_kind"] == "deterministic_demo"
    assert failed_detail["retryable"] is False

    unaudited = client.get(
        f"/api/projects/{ACME_UNAUDITED_PROJECT_ID}", headers=alice_headers
    ).json()
    assert unaudited["latest_audit"] is None


def test_demo_seed_is_idempotent_and_preserves_recommendation_progress() -> None:
    seed()
    with SessionLocal() as db:
        audit = db.scalar(
            select(Audit)
            .options(selectinload(Audit.recommendations))
            .where(Audit.id == DEMO_AUDIT_IDS["prj_acme_demo"])
        )
        assert audit is not None
        audit.recommendations[0].status = RecommendationStatus.completed
        db.commit()

    seed()

    with SessionLocal() as db:
        audits = list(
            db.scalars(
                select(Audit)
                .options(
                    selectinload(Audit.pages),
                    selectinload(Audit.prompts),
                    selectinload(Audit.findings),
                    selectinload(Audit.recommendations),
                    selectinload(Audit.events),
                )
                .where(Audit.idempotency_key == DEMO_AUDIT_IDEMPOTENCY_KEY)
                .order_by(Audit.id)
            ).all()
        )
        assert len(audits) == 3
        completed_audits = [audit for audit in audits if audit.status == AuditStatus.completed]
        assert len(completed_audits) == 2
        assert all(len(audit.pages) == len(audit.prompts) == 2 for audit in completed_audits)
        assert all(
            len(audit.findings) == len(audit.recommendations) == 2 for audit in completed_audits
        )
        assert all(
            sum(event.event_type == AuditEventType.audit_completed for event in audit.events) == 1
            for audit in completed_audits
        )
        acme = next(audit for audit in audits if audit.id == DEMO_AUDIT_IDS["prj_acme_demo"])
        assert any(
            recommendation.status == RecommendationStatus.completed
            for recommendation in acme.recommendations
        )
        assert db.scalar(select(func.count()).select_from(Audit)) == 3
