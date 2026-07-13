import argparse

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.database import SessionLocal
from app.models import Audit, AuditStatus
from app.services import refresh_completed_simulated_audit


def refresh_project(project_id: str) -> list[tuple[str, int]]:
    if get_settings().app_env == "production":
        raise RuntimeError("Simulated audit refresh is disabled in production")

    with SessionLocal() as db:
        audits = list(
            db.scalars(
                select(Audit)
                .options(
                    selectinload(Audit.project),
                    selectinload(Audit.pages),
                    selectinload(Audit.prompts),
                    selectinload(Audit.findings),
                    selectinload(Audit.recommendations),
                    selectinload(Audit.events),
                )
                .where(
                    Audit.project_id == project_id,
                    Audit.status == AuditStatus.completed,
                )
                .order_by(Audit.created_at, Audit.id)
            ).all()
        )
        refreshed = [(audit.id, refresh_completed_simulated_audit(audit)) for audit in audits]
        db.commit()
        return refreshed


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Refresh persisted outputs created by the local simulated audit provider."
    )
    parser.add_argument("project_id")
    args = parser.parse_args()
    for audit_id, score in refresh_project(args.project_id):
        print(f"{audit_id}: {score}")


if __name__ == "__main__":
    main()
